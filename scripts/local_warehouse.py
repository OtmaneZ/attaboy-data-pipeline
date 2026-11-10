"""Entrepôt local (DuckDB) — la démo complète sans compte Snowflake.

Même structure que Snowflake (schémas raw / meta, mêmes colonnes que sql/001 et
sql/002) dans un seul fichier DuckDB. Sert à trois choses :

- faire tourner la démo et les captures sans dépenser un crédit ;
- développer et tester les modèles dbt hors ligne (`dbt build --target local`) ;
- exécuter le pipeline complet dans la CI.

Les données réelles du restaurant ne passent jamais par ici : elles vont
directement dans Snowflake via scripts/ingest_clover.py.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCAL_DB = REPO_ROOT / "local" / "attaboy_demo.duckdb"
PIPELINE_NAME = "load_demo"

# Colonnes typées de chaque table brute (hors payload et colonnes techniques).
RAW_TABLES: dict[str, dict[str, str]] = {
    "raw_clover_orders": {
        "clover_order_id": "VARCHAR",
        "merchant_id": "VARCHAR",
        "created_time": "TIMESTAMPTZ",
        "modified_time": "TIMESTAMPTZ",
        "client_created_time": "TIMESTAMPTZ",
        "state": "VARCHAR",
        "currency": "VARCHAR",
        "total_cents": "BIGINT",
        "payment_state": "VARCHAR",
        "title": "VARCHAR",
        "note": "VARCHAR",
    },
    "raw_clover_line_items": {
        "clover_line_item_id": "VARCHAR",
        "clover_order_id": "VARCHAR",
        "merchant_id": "VARCHAR",
        "name": "VARCHAR",
        "price_cents": "BIGINT",
        "unit_qty": "DECIMAL(18,6)",
        "item_id": "VARCHAR",
        "created_time": "TIMESTAMPTZ",
        "modified_time": "TIMESTAMPTZ",
    },
    "raw_clover_payments": {
        "clover_payment_id": "VARCHAR",
        "clover_order_id": "VARCHAR",
        "merchant_id": "VARCHAR",
        "amount_cents": "BIGINT",
        "tip_amount_cents": "BIGINT",
        "tax_amount_cents": "BIGINT",
        "result": "VARCHAR",
        "tender_type": "VARCHAR",
        "created_time": "TIMESTAMPTZ",
        "modified_time": "TIMESTAMPTZ",
    },
}

SQL_PIPELINE_RUNS = """
CREATE TABLE IF NOT EXISTS meta.pipeline_runs (
    run_id          VARCHAR NOT NULL PRIMARY KEY,
    pipeline_name   VARCHAR NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL,
    finished_at     TIMESTAMPTZ,
    status          VARCHAR NOT NULL,
    rows_processed  BIGINT,
    error_message   VARCHAR
)
"""


def local_db_path() -> Path:
    """Chemin du fichier DuckDB (ATTABOY_LOCAL_DB, sinon local/attaboy_demo.duckdb)."""
    raw = os.environ.get("ATTABOY_LOCAL_DB", "").strip()
    return Path(raw).expanduser() if raw else DEFAULT_LOCAL_DB


def connect_local(path: Optional[Path] = None, *, read_only: bool = False) -> Any:
    import duckdb

    path = path or local_db_path()
    if not read_only:
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(path), read_only=read_only)
    conn.execute("SET TimeZone = 'UTC'")
    return conn


def create_raw_table_sql(table: str) -> str:
    columns = RAW_TABLES[table]
    key = next(iter(columns))
    cols = ",\n    ".join(f"{name} {dtype}" for name, dtype in columns.items())
    return (
        f"CREATE TABLE IF NOT EXISTS raw.{table} (\n    {cols},\n"
        "    payload JSON NOT NULL,\n"
        "    _ingested_at TIMESTAMPTZ NOT NULL,\n"
        "    _source_request_id VARCHAR NOT NULL,\n"
        f"    PRIMARY KEY ({key})\n)"
    )


def ensure_schema(conn: Any) -> None:
    conn.execute("CREATE SCHEMA IF NOT EXISTS raw")
    conn.execute("CREATE SCHEMA IF NOT EXISTS meta")
    for table in RAW_TABLES:
        conn.execute(create_raw_table_sql(table))
    conn.execute(SQL_PIPELINE_RUNS)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _write_ndjson(rows: Sequence[Mapping[str, Any]], path: Path) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            out = {k: v for k, v in row.items() if k not in ("payload", "source_request_id")}
            out["payload"] = json.dumps(row["payload"], ensure_ascii=False, default=_json_default)
            out["_source_request_id"] = row["source_request_id"]
            fh.write(json.dumps(out, ensure_ascii=False, default=_json_default) + "\n")


def _replace_rows(conn: Any, table: str, rows: Sequence[Mapping[str, Any]], merchant_id: str, tmp: Path) -> None:
    """Remplace toutes les lignes du marchand : rejouer le chargement donne le même résultat."""
    conn.execute(f"DELETE FROM raw.{table} WHERE merchant_id = ?", [merchant_id])
    if not rows:
        return
    file = tmp / f"{table}.ndjson"
    _write_ndjson(rows, file)
    columns = RAW_TABLES[table]
    read_columns = {name: "VARCHAR" for name in columns} | {"payload": "VARCHAR", "_source_request_id": "VARCHAR"}
    select = ", ".join(f"CAST({name} AS {dtype}) AS {name}" for name, dtype in columns.items())
    conn.execute(
        f"""
        INSERT INTO raw.{table}
        SELECT {select}, CAST(payload AS JSON), now(), _source_request_id
        FROM read_json(?, format = 'newline_delimited', columns = {read_columns!r})
        """,
        [str(file)],
    )


def load_demo_orders(
    orders: Sequence[Mapping[str, Any]],
    *,
    merchant_id: str,
    path: Optional[Path] = None,
) -> tuple[Path, int]:
    """Charge des commandes au format Clover dans l'entrepôt local. Retourne (fichier, lignes)."""
    from scripts.ingest_clover import extract_from_orders

    path = path or local_db_path()
    run_id = f"demo-{uuid.uuid4()}"
    started_at = datetime.now(timezone.utc)
    order_rows, line_rows, payment_rows = extract_from_orders(
        orders, merchant_id=merchant_id, source_request_id=run_id
    )
    total = len(order_rows) + len(line_rows) + len(payment_rows)

    conn = connect_local(path)
    try:
        ensure_schema(conn)
        with tempfile.TemporaryDirectory() as tmp:
            conn.execute("BEGIN")
            try:
                for table, rows in (
                    ("raw_clover_line_items", line_rows),
                    ("raw_clover_payments", payment_rows),
                    ("raw_clover_orders", order_rows),
                ):
                    _replace_rows(conn, table, rows, merchant_id, Path(tmp))
                conn.execute(
                    "INSERT INTO meta.pipeline_runs VALUES (?, ?, ?, now(), 'success', ?, NULL)",
                    [run_id, PIPELINE_NAME, started_at, total],
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
    finally:
        conn.close()
    return path, total
