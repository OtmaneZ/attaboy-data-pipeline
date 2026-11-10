from __future__ import annotations

import json
from datetime import date

import pytest

duckdb = pytest.importorskip("duckdb")

from scripts.demo_data import DEMO_MERCHANT_ID, DemoGenerator  # noqa: E402
from scripts.local_warehouse import connect_local, create_raw_table_sql, load_demo_orders  # noqa: E402

DAY = date(2026, 9, 12)


def _orders():
    return DemoGenerator(seed=3).generate(DAY, DAY)


def _count(path, table: str) -> int:
    conn = connect_local(path, read_only=True)
    try:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_load_creates_raw_tables_and_logs_run(tmp_path) -> None:
    orders = _orders()
    path, rows = load_demo_orders(orders, merchant_id=DEMO_MERCHANT_ID, path=tmp_path / "demo.duckdb")

    n_lines = sum(len(o["lineItems"]["elements"]) for o in orders)
    assert rows == len(orders) * 2 + n_lines
    assert _count(path, "raw.raw_clover_orders") == len(orders)
    assert _count(path, "raw.raw_clover_line_items") == n_lines
    assert _count(path, "raw.raw_clover_payments") == len(orders)

    conn = connect_local(path, read_only=True)
    try:
        run = conn.execute("SELECT pipeline_name, status, rows_processed FROM meta.pipeline_runs").fetchall()
        merchants = conn.execute("SELECT DISTINCT merchant_id FROM raw.raw_clover_orders").fetchall()
    finally:
        conn.close()
    assert run == [("load_demo", "success", rows)]
    assert merchants == [(DEMO_MERCHANT_ID,)]


def test_reload_is_idempotent(tmp_path) -> None:
    path = tmp_path / "demo.duckdb"
    orders = _orders()
    load_demo_orders(orders, merchant_id=DEMO_MERCHANT_ID, path=path)
    load_demo_orders(orders, merchant_id=DEMO_MERCHANT_ID, path=path)

    assert _count(path, "raw.raw_clover_orders") == len(orders)
    assert _count(path, "meta.pipeline_runs") == 2


def test_payload_keeps_the_full_clover_json(tmp_path) -> None:
    orders = _orders()
    path, _ = load_demo_orders(orders, merchant_id=DEMO_MERCHANT_ID, path=tmp_path / "demo.duckdb")

    conn = connect_local(path, read_only=True)
    try:
        payload, created = conn.execute(
            "SELECT payload, created_time FROM raw.raw_clover_orders WHERE clover_order_id = ?", [orders[0]["id"]]
        ).fetchone()
    finally:
        conn.close()
    stored = json.loads(payload)
    assert stored["orderType"]["label"] == orders[0]["orderType"]["label"]
    assert stored["lineItems"]["elements"][0]["id"] == orders[0]["lineItems"]["elements"][0]["id"]
    assert int(created.timestamp() * 1000) == orders[0]["createdTime"]


def test_raw_table_ddl_mirrors_snowflake_columns() -> None:
    ddl = create_raw_table_sql("raw_clover_payments")
    for column in ("clover_payment_id", "tip_amount_cents", "payload JSON", "_ingested_at", "_source_request_id"):
        assert column in ddl
    assert "PRIMARY KEY (clover_payment_id)" in ddl
