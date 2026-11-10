#!/usr/bin/env python3
"""Attaboy Mission 3 — ingest incrémental Clover → Snowflake RAW.RAW_CLOVER_*.

Sandbox d'abord. Secrets via /opt/clients/attaboy/.env (jamais loggés).
Chargement : INSERT multi-lignes dans des tables temporaires, puis MERGE
idempotent dans une seule transaction.
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterator, Mapping, Optional, Sequence

import httpx

from scripts.snowflake_utils import (
    PipelineRunStore,
    SnowflakeSettings,
    connect,
    load_attaboy_env,
    optional_env,
    require_env,
    sanitize_error,
)

PIPELINE_NAME = "ingest_clover"
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_PAGE_LIMIT = 100
USER_AGENT = "attaboy-ingest-clover/1.0"

log = logging.getLogger("attaboy.ingest_clover")


# ---------------------------------------------------------------------------
# Env
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Settings:
    snowflake: SnowflakeSettings
    clover_base_url: str
    clover_merchant_id: str
    clover_api_token: str
    lookback_days: int
    page_limit: int = DEFAULT_PAGE_LIMIT

    @classmethod
    def from_env(cls) -> Settings:
        load_attaboy_env()

        lookback_raw = optional_env("ATTABOY_CLOVER_LOOKBACK_DAYS") or str(DEFAULT_LOOKBACK_DAYS)
        try:
            lookback_days = int(lookback_raw)
        except ValueError as exc:
            raise SystemExit("ATTABOY_CLOVER_LOOKBACK_DAYS doit être un entier") from exc
        if lookback_days < 1:
            raise SystemExit("ATTABOY_CLOVER_LOOKBACK_DAYS doit être >= 1")

        return cls(
            snowflake=SnowflakeSettings.from_env(),
            clover_base_url=require_env("CLOVER_BASE_URL").rstrip("/"),
            clover_merchant_id=require_env("CLOVER_MERCHANT_ID"),
            clover_api_token=require_env("CLOVER_API_TOKEN"),
            lookback_days=lookback_days,
        )

    def secrets(self) -> tuple[str, ...]:
        return (self.clover_api_token, *self.snowflake.secrets())


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def ms_to_timestamptz(value: Any) -> Optional[datetime]:
    """Convertit un epoch Clover (ms) en datetime UTC aware."""
    if value is None or value == "":
        return None
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


def timestamptz_to_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def compute_modified_since(
    last_success: Optional[datetime],
    *,
    now: Optional[datetime] = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> datetime:
    """Watermark inclusif côté filtre: modifiedTime > ms(watermark - 1ms) via > ms."""
    now = now or datetime.now(timezone.utc)
    if last_success is not None:
        if last_success.tzinfo is None:
            last_success = last_success.replace(tzinfo=timezone.utc)
        return last_success
    return now - timedelta(days=lookback_days)


# ---------------------------------------------------------------------------
# Mapping Clover → rows
# ---------------------------------------------------------------------------


def _elements(container: Any) -> list[dict[str, Any]]:
    if container is None:
        return []
    if isinstance(container, list):
        return [x for x in container if isinstance(x, dict)]
    if isinstance(container, Mapping):
        elems = container.get("elements")
        if isinstance(elems, list):
            return [x for x in elems if isinstance(x, dict)]
    return []


def _nested_id(obj: Any) -> Optional[str]:
    if isinstance(obj, Mapping) and obj.get("id") is not None:
        return str(obj["id"])
    return None


def map_order(
    order: Mapping[str, Any],
    *,
    merchant_id: str,
    source_request_id: str,
) -> dict[str, Any]:
    return {
        "clover_order_id": str(order["id"]),
        "merchant_id": merchant_id,
        "created_time": ms_to_timestamptz(order.get("createdTime")),
        "modified_time": ms_to_timestamptz(order.get("modifiedTime")),
        "client_created_time": ms_to_timestamptz(order.get("clientCreatedTime")),
        "state": order.get("state"),
        "currency": order.get("currency"),
        "total_cents": int(order["total"]) if order.get("total") is not None else None,
        "payment_state": order.get("paymentState"),
        "title": order.get("title"),
        "note": order.get("note"),
        "payload": dict(order),
        "source_request_id": source_request_id,
    }


def map_line_item(
    item: Mapping[str, Any],
    *,
    order_id: str,
    merchant_id: str,
    source_request_id: str,
) -> dict[str, Any]:
    unit_qty = item.get("unitQty")
    if unit_qty is not None:
        unit_qty = Decimal(str(unit_qty))
    return {
        "clover_line_item_id": str(item["id"]),
        "clover_order_id": order_id,
        "merchant_id": merchant_id,
        "name": item.get("name"),
        "price_cents": int(item["price"]) if item.get("price") is not None else None,
        "unit_qty": unit_qty,
        "item_id": _nested_id(item.get("item")),
        "created_time": ms_to_timestamptz(item.get("createdTime")),
        "modified_time": ms_to_timestamptz(item.get("modifiedTime")),
        "payload": dict(item),
        "source_request_id": source_request_id,
    }


def map_payment(
    payment: Mapping[str, Any],
    *,
    order_id: str,
    merchant_id: str,
    source_request_id: str,
) -> dict[str, Any]:
    tender = payment.get("tender")
    tender_type = None
    if isinstance(tender, Mapping):
        tender_type = tender.get("label") or tender.get("labelKey") or tender.get("type")
    return {
        "clover_payment_id": str(payment["id"]),
        "clover_order_id": order_id,
        "merchant_id": merchant_id,
        "amount_cents": int(payment["amount"]) if payment.get("amount") is not None else None,
        "tip_amount_cents": int(payment["tipAmount"]) if payment.get("tipAmount") is not None else None,
        "tax_amount_cents": int(payment["taxAmount"]) if payment.get("taxAmount") is not None else None,
        "result": payment.get("result"),
        "tender_type": tender_type,
        "created_time": ms_to_timestamptz(payment.get("createdTime")),
        "modified_time": ms_to_timestamptz(payment.get("modifiedTime")),
        "payload": dict(payment),
        "source_request_id": source_request_id,
    }


def extract_from_orders(
    orders: Sequence[Mapping[str, Any]],
    *,
    merchant_id: str,
    source_request_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    order_rows: list[dict[str, Any]] = []
    line_rows: list[dict[str, Any]] = []
    payment_rows: list[dict[str, Any]] = []
    for order in orders:
        if not order.get("id"):
            continue
        order_rows.append(
            map_order(order, merchant_id=merchant_id, source_request_id=source_request_id)
        )
        oid = str(order["id"])
        for item in _elements(order.get("lineItems")):
            if item.get("id"):
                line_rows.append(
                    map_line_item(
                        item,
                        order_id=oid,
                        merchant_id=merchant_id,
                        source_request_id=source_request_id,
                    )
                )
        for payment in _elements(order.get("payments")):
            if payment.get("id"):
                payment_rows.append(
                    map_payment(
                        payment,
                        order_id=oid,
                        merchant_id=merchant_id,
                        source_request_id=source_request_id,
                    )
                )
    return order_rows, line_rows, payment_rows


# ---------------------------------------------------------------------------
# Clover HTTP
# ---------------------------------------------------------------------------


class CloverClient:
    def __init__(
        self,
        *,
        base_url: str,
        merchant_id: str,
        api_token: str,
        page_limit: int = DEFAULT_PAGE_LIMIT,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.merchant_id = merchant_id
        self.page_limit = page_limit
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {api_token}",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            timeout=60.0,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> CloverClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def iter_orders(self, modified_since: datetime) -> Iterator[dict[str, Any]]:
        """Yield orders with expand=lineItems,payments, filter modifiedTime>ms."""
        modified_ms = timestamptz_to_ms(modified_since)
        offset = 0
        while True:
            params = {
                "expand": "lineItems,payments",
                "filter": f"modifiedTime>{modified_ms}",
                "limit": str(self.page_limit),
                "offset": str(offset),
            }
            url = f"{self.base_url}/v3/merchants/{self.merchant_id}/orders"
            response = self._client.get(url, params=params)
            # Ne jamais inclure Authorization dans les messages d'erreur
            if response.status_code >= 400:
                raise RuntimeError(
                    f"Clover API HTTP {response.status_code} on GET {url} "
                    f"(offset={offset})"
                )
            payload = response.json()
            elements = _elements(payload)
            for order in elements:
                yield order
            if len(elements) < self.page_limit:
                break
            offset += self.page_limit




# ---------------------------------------------------------------------------
# Snowflake — chargement temp table + MERGE
# ---------------------------------------------------------------------------

INSERT_BATCH_SIZE = 100  # garde chaque INSERT multi-lignes loin de la limite de taille de requête


@dataclass(frozen=True)
class RawTable:
    target: str
    key: str
    # (colonne, type Snowflake) hors payload / colonnes techniques
    columns: tuple[tuple[str, str], ...]

    @property
    def staging(self) -> str:
        schema, name = self.target.split(".")
        return f"{schema}.stg_{name}"

    @property
    def column_names(self) -> list[str]:
        return [c for c, _ in self.columns]

    def create_staging_sql(self) -> str:
        cols = ",\n    ".join(f"{c} {t}" for c, t in self.columns)
        return (
            f"CREATE OR REPLACE TEMPORARY TABLE {self.staging} (\n    {cols},\n"
            "    payload_json VARCHAR,\n    _source_request_id VARCHAR\n)"
        )

    def insert_staging_sql(self) -> str:
        names = self.column_names + ["payload_json", "_source_request_id"]
        placeholders = ", ".join(f"%({n})s" for n in names)
        return f"INSERT INTO {self.staging} ({', '.join(names)}) VALUES ({placeholders})"

    def merge_sql(self) -> str:
        names = self.column_names
        select_cols = ", ".join(names)
        update_set = ",\n    ".join(f"{c} = s.{c}" for c in names if c != self.key)
        insert_cols = ", ".join(names + ["payload", "_source_request_id", "_ingested_at"])
        insert_vals = ", ".join(
            [f"s.{c}" for c in names] + ["s.payload", "s._source_request_id", "CURRENT_TIMESTAMP()"]
        )
        return f"""
MERGE INTO {self.target} t
USING (
    SELECT {select_cols}, PARSE_JSON(payload_json) AS payload, _source_request_id
    FROM {self.staging}
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY {self.key} ORDER BY modified_time DESC NULLS LAST
    ) = 1
) s
ON t.{self.key} = s.{self.key}
WHEN MATCHED THEN UPDATE SET
    {update_set},
    payload = s.payload,
    _source_request_id = s._source_request_id,
    _ingested_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT ({insert_cols})
VALUES ({insert_vals})
"""


RAW_ORDERS = RawTable(
    target="raw.raw_clover_orders",
    key="clover_order_id",
    columns=(
        ("clover_order_id", "VARCHAR"),
        ("merchant_id", "VARCHAR"),
        ("created_time", "TIMESTAMP_TZ"),
        ("modified_time", "TIMESTAMP_TZ"),
        ("client_created_time", "TIMESTAMP_TZ"),
        ("state", "VARCHAR"),
        ("currency", "VARCHAR"),
        ("total_cents", "NUMBER(38,0)"),
        ("payment_state", "VARCHAR"),
        ("title", "VARCHAR"),
        ("note", "VARCHAR"),
    ),
)

RAW_LINE_ITEMS = RawTable(
    target="raw.raw_clover_line_items",
    key="clover_line_item_id",
    columns=(
        ("clover_line_item_id", "VARCHAR"),
        ("clover_order_id", "VARCHAR"),
        ("merchant_id", "VARCHAR"),
        ("name", "VARCHAR"),
        ("price_cents", "NUMBER(38,0)"),
        ("unit_qty", "NUMBER(18,6)"),
        ("item_id", "VARCHAR"),
        ("created_time", "TIMESTAMP_TZ"),
        ("modified_time", "TIMESTAMP_TZ"),
    ),
)

RAW_PAYMENTS = RawTable(
    target="raw.raw_clover_payments",
    key="clover_payment_id",
    columns=(
        ("clover_payment_id", "VARCHAR"),
        ("clover_order_id", "VARCHAR"),
        ("merchant_id", "VARCHAR"),
        ("amount_cents", "NUMBER(38,0)"),
        ("tip_amount_cents", "NUMBER(38,0)"),
        ("tax_amount_cents", "NUMBER(38,0)"),
        ("result", "VARCHAR"),
        ("tender_type", "VARCHAR"),
        ("created_time", "TIMESTAMP_TZ"),
        ("modified_time", "TIMESTAMP_TZ"),
    ),
)


def _row_for_db(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["payload_json"] = json.dumps(out.pop("payload"), default=str, ensure_ascii=False)
    out["_source_request_id"] = out.pop("source_request_id")
    return out


def _batches(rows: Sequence[dict[str, Any]], size: int) -> Iterator[Sequence[dict[str, Any]]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


class RawLoader:
    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def upsert_all(
        self,
        orders: Sequence[dict[str, Any]],
        line_items: Sequence[dict[str, Any]],
        payments: Sequence[dict[str, Any]],
    ) -> int:
        """Stage puis MERGE (orders → line_items → payments). Retourne le total de lignes."""
        work = [
            (spec, rows)
            for spec, rows in ((RAW_ORDERS, orders), (RAW_LINE_ITEMS, line_items), (RAW_PAYMENTS, payments))
            if rows
        ]
        if not work:
            return 0

        with self.conn.cursor() as cur:
            # DDL = commit implicite en Snowflake : on stage AVANT d'ouvrir la transaction.
            for spec, rows in work:
                cur.execute(spec.create_staging_sql())
                db_rows = [_row_for_db(r) for r in rows]
                for batch in _batches(db_rows, INSERT_BATCH_SIZE):
                    cur.executemany(spec.insert_staging_sql(), batch)

            cur.execute("BEGIN")
            try:
                for spec, _rows in work:
                    cur.execute(spec.merge_sql())
                cur.execute("COMMIT")
            except Exception:
                cur.execute("ROLLBACK")
                raise
        return sum(len(rows) for _spec, rows in work)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_ingest(
    settings: Settings,
    *,
    conn: Any = None,
    clover: Optional[CloverClient] = None,
    source_request_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> int:
    """Exécute un run complet. Retourne rows_processed. Lève en cas d'échec API/DB."""
    owns_conn = conn is None
    owns_clover = clover is None
    source_request_id = source_request_id or str(uuid.uuid4())
    run_id = source_request_id
    now = now or datetime.now(timezone.utc)
    store: Optional[PipelineRunStore] = None
    started = False

    try:
        if conn is None:
            conn = connect(settings.snowflake, query_tag=f"attaboy:{PIPELINE_NAME}")
        store = PipelineRunStore(conn, PIPELINE_NAME)

        # Watermark = début du dernier run réussi (pas sa fin) : une commande modifiée
        # pendant le run précédent est re-lue ; le MERGE rend la relecture sans effet.
        last_success = store.last_success_started_at()
        store.start_run(run_id, now)
        started = True

        modified_since = compute_modified_since(
            last_success, now=now, lookback_days=settings.lookback_days
        )
        log.info(
            "run_id=%s modified_since=%s lookback_days=%s",
            run_id,
            modified_since.isoformat(),
            settings.lookback_days,
        )

        if clover is None:
            clover = CloverClient(
                base_url=settings.clover_base_url,
                merchant_id=settings.clover_merchant_id,
                api_token=settings.clover_api_token,
                page_limit=settings.page_limit,
            )

        orders = list(clover.iter_orders(modified_since))
        order_rows, line_rows, payment_rows = extract_from_orders(
            orders,
            merchant_id=settings.clover_merchant_id,
            source_request_id=source_request_id,
        )
        rows_processed = RawLoader(conn).upsert_all(order_rows, line_rows, payment_rows)
        store.finish_run(
            run_id,
            status="success",
            rows_processed=rows_processed,
            error_message=None,
        )
        log.info(
            "success run_id=%s orders=%s line_items=%s payments=%s rows=%s",
            run_id,
            len(order_rows),
            len(line_rows),
            len(payment_rows),
            rows_processed,
        )
        return rows_processed
    except Exception as exc:
        if store is not None and started:
            store.finish_run(
                run_id,
                status="failed",
                rows_processed=None,
                error_message=sanitize_error(exc, *settings.secrets()),
            )
        raise
    finally:
        if owns_clover and clover is not None:
            clover.close()
        if owns_conn and conn is not None:
            conn.close()


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    configure_logging()
    _ = argv  # CLI sans args pour V1
    settings = Settings.from_env()
    try:
        rows = run_ingest(settings)
    except SystemExit:
        raise
    except Exception as exc:
        log.error("ingest failed: %s", sanitize_error(exc, *settings.secrets()))
        return 1
    print(json.dumps({"pipeline": PIPELINE_NAME, "status": "success", "rows_processed": rows}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
