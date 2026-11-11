from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx

from scripts.ingest_clover import (
    RAW_ORDERS,
    CloverClient,
    RawLoader,
    Settings,
    compute_modified_since,
    extract_from_orders,
    map_line_item,
    map_order,
    map_payment,
    ms_to_timestamptz,
    run_ingest,
    timestamptz_to_ms,
    write_stage_file,
)
from scripts.snowflake_utils import SnowflakeSettings, sanitize_error
from tests.fakes import FakeConn


SAMPLE_ORDER: dict[str, Any] = {
    "id": "ORD1",
    "currency": "USD",
    "total": 1500,
    "state": "locked",
    "paymentState": "paid",
    "title": "Table 1",
    "note": None,
    "createdTime": 1_700_000_000_000,
    "modifiedTime": 1_700_000_100_000,
    "clientCreatedTime": 1_700_000_000_000,
    "lineItems": {
        "elements": [
            {
                "id": "LI1",
                "name": "Pizza",
                "price": 1500,
                "unitQty": 1000,
                "item": {"id": "ITEM1"},
                "createdTime": 1_700_000_000_000,
                "modifiedTime": 1_700_000_050_000,
            }
        ]
    },
    "payments": {
        "elements": [
            {
                "id": "PAY1",
                "amount": 1500,
                "tipAmount": 0,
                "taxAmount": 100,
                "result": "SUCCESS",
                "tender": {"label": "Credit Card"},
                "createdTime": 1_700_000_080_000,
                "modifiedTime": 1_700_000_090_000,
            }
        ]
    },
}


def test_ms_to_timestamptz_and_back() -> None:
    ms = 1_700_000_000_000
    dt = ms_to_timestamptz(ms)
    assert dt is not None
    assert dt.tzinfo is not None
    assert timestamptz_to_ms(dt) == ms
    assert ms_to_timestamptz(None) is None
    assert ms_to_timestamptz("bad") is None


def test_compute_modified_since_lookback_and_watermark() -> None:
    now = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
    since = compute_modified_since(None, now=now, lookback_days=7)
    assert since == datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)

    last = datetime(2026, 8, 6, 5, 0, tzinfo=timezone.utc)
    assert compute_modified_since(last, now=now, lookback_days=7) == last


def test_extract_and_map_order_tree() -> None:
    orders, lines, payments = extract_from_orders(
        [SAMPLE_ORDER],
        merchant_id="MERCH1",
        source_request_id="req-1",
    )
    assert len(orders) == 1
    assert orders[0]["clover_order_id"] == "ORD1"
    assert orders[0]["total_cents"] == 1500
    assert orders[0]["merchant_id"] == "MERCH1"
    assert orders[0]["source_request_id"] == "req-1"
    assert isinstance(orders[0]["payload"], dict)

    assert len(lines) == 1
    assert lines[0]["clover_line_item_id"] == "LI1"
    assert lines[0]["clover_order_id"] == "ORD1"
    assert lines[0]["item_id"] == "ITEM1"
    assert lines[0]["unit_qty"] == Decimal("1000")

    assert len(payments) == 1
    assert payments[0]["clover_payment_id"] == "PAY1"
    assert payments[0]["tender_type"] == "Credit Card"
    assert payments[0]["amount_cents"] == 1500


def test_map_negative_refund_amount_allowed() -> None:
    pay = map_payment(
        {"id": "R1", "amount": -500, "result": "SUCCESS"},
        order_id="ORD1",
        merchant_id="M",
        source_request_id="r",
    )
    assert pay["amount_cents"] == -500


def test_sanitize_error_redacts_secrets() -> None:
    token = "super-secret-token"
    password = "db-pass-xyz"
    exc = RuntimeError(f"boom {token} password={password}")
    msg = sanitize_error(exc, token, password)
    assert token not in msg
    assert password not in msg
    assert "***" in msg


@respx.mock
def test_clover_client_pagination() -> None:
    base = "https://apisandbox.dev.clover.com"
    merchant = "MERCH1"
    route = respx.get(url__regex=rf"{base}/v3/merchants/{merchant}/orders.*").mock(
        side_effect=[
            httpx.Response(
                200,
                json={"elements": [{"id": "A", "modifiedTime": 1}, {"id": "B", "modifiedTime": 2}]},
            ),
            httpx.Response(200, json={"elements": [{"id": "C", "modifiedTime": 3}]}),
        ]
    )
    client = CloverClient(
        base_url=base,
        merchant_id=merchant,
        api_token="token",
        page_limit=2,
        client=httpx.Client(),
    )
    try:
        since = datetime(2026, 1, 1, tzinfo=timezone.utc)
        ids = [o["id"] for o in client.iter_orders(since)]
    finally:
        client.close()

    assert ids == ["A", "B", "C"]
    assert route.call_count == 2
    first_request = route.calls[0].request
    assert "expand=lineItems%2Cpayments" in str(first_request.url) or "expand=lineItems,payments" in str(
        first_request.url
    )
    assert "modifiedTime%3E" in str(first_request.url) or "modifiedTime>" in str(first_request.url)


@respx.mock
def test_clover_client_http_error() -> None:
    base = "https://apisandbox.dev.clover.com"
    merchant = "MERCH1"
    respx.get(url__regex=rf"{base}/v3/merchants/{merchant}/orders.*").mock(
        return_value=httpx.Response(401, json={"message": "denied"})
    )
    client = CloverClient(
        base_url=base,
        merchant_id=merchant,
        api_token="token",
        client=httpx.Client(),
    )
    try:
        with pytest.raises(RuntimeError, match="HTTP 401"):
            list(client.iter_orders(datetime(2026, 1, 1, tzinfo=timezone.utc)))
    finally:
        client.close()


def _settings() -> Settings:
    return Settings(
        snowflake=SnowflakeSettings(
            account="org-acct",
            user="ATTABOY_PIPELINE_SVC",
            role="ATTABOY_PIPELINE",
            warehouse="ATTABOY_WH",
            database="ATTABOY_DW",
            private_key_path="/tmp/key.p8",
            private_key_passphrase="keypass",
        ),
        clover_base_url="https://apisandbox.dev.clover.com",
        clover_merchant_id="MERCH1",
        clover_api_token="tokensecret",
        lookback_days=7,
        page_limit=100,
    )


@respx.mock
def test_run_ingest_success_upsert_order() -> None:
    base = "https://apisandbox.dev.clover.com"
    respx.get(url__regex=rf"{base}/v3/merchants/MERCH1/orders.*").mock(
        return_value=httpx.Response(200, json={"elements": [SAMPLE_ORDER]})
    )
    conn = FakeConn(last_success=datetime(2026, 8, 1, tzinfo=timezone.utc))
    settings = _settings()
    http = httpx.Client()
    clover = CloverClient(
        base_url=base,
        merchant_id="MERCH1",
        api_token="tokensecret",
        client=http,
    )
    try:
        rows = run_ingest(
            settings,
            conn=conn,  # type: ignore[arg-type]
            clover=clover,
            source_request_id="req-xyz",
            now=datetime(2026, 8, 7, tzinfo=timezone.utc),
        )
    finally:
        clover.close()

    assert rows == 3  # 1 order + 1 line + 1 payment
    # Ordre : orders puis line_items puis payments
    assert [m.split()[2] for m in conn.merges] == [
        "raw.raw_clover_orders",
        "raw.raw_clover_line_items",
        "raw.raw_clover_payments",
    ]
    # Les MERGE sont dans une transaction explicite, ouverte après le staging (DDL)
    stmts = conn.statements()
    begin = stmts.index("BEGIN")
    assert all(not s.startswith("CREATE") for s in stmts[begin:])
    assert stmts[-2] == "COMMIT"  # puis UPDATE meta.pipeline_runs

    staged_order = conn.staged[0][1][0]
    assert staged_order["clover_order_id"] == "ORD1"
    assert json.loads(staged_order["payload_json"])["id"] == "ORD1"
    assert staged_order["_source_request_id"] == "req-xyz"

    run_id, pipeline_name, _started_at = conn.started[0]
    assert run_id == "req-xyz"
    assert pipeline_name == "ingest_clover"
    finished_at, status, rows_processed, error_message, finished_run_id = conn.finished[-1]
    assert status == "success"
    assert rows_processed == 3
    assert error_message is None
    assert finished_run_id == "req-xyz"


@respx.mock
def test_run_ingest_uses_last_success_start_as_watermark() -> None:
    base = "https://apisandbox.dev.clover.com"
    route = respx.get(url__regex=rf"{base}/v3/merchants/MERCH1/orders.*").mock(
        return_value=httpx.Response(200, json={"elements": []})
    )
    last_start = datetime(2026, 8, 6, 9, 0, tzinfo=timezone.utc)
    conn = FakeConn(last_success=last_start)
    clover = CloverClient(base_url=base, merchant_id="MERCH1", api_token="t", client=httpx.Client())
    try:
        rows = run_ingest(
            _settings(),
            conn=conn,  # type: ignore[arg-type]
            clover=clover,
            now=datetime(2026, 8, 7, 9, 0, tzinfo=timezone.utc),
        )
    finally:
        clover.close()

    assert rows == 0
    assert not conn.merges  # rien à charger : aucun MERGE ni transaction
    assert f"modifiedTime%3E{timestamptz_to_ms(last_start)}" in str(route.calls[0].request.url) or (
        f"modifiedTime>{timestamptz_to_ms(last_start)}" in str(route.calls[0].request.url)
    )


@respx.mock
def test_run_ingest_merge_failure_rolls_back_and_marks_failed() -> None:
    base = "https://apisandbox.dev.clover.com"
    respx.get(url__regex=rf"{base}/v3/merchants/MERCH1/orders.*").mock(
        return_value=httpx.Response(200, json={"elements": [SAMPLE_ORDER]})
    )
    conn = FakeConn(fail_on_merge=True)
    clover = CloverClient(base_url=base, merchant_id="MERCH1", api_token="t", client=httpx.Client())
    try:
        with pytest.raises(RuntimeError, match="merge exploded"):
            run_ingest(_settings(), conn=conn, clover=clover)  # type: ignore[arg-type]
    finally:
        clover.close()

    assert "ROLLBACK" in conn.statements()
    assert "COMMIT" not in conn.statements()
    assert conn.finished[-1][1] == "failed"


@respx.mock
def test_run_ingest_api_failure_marks_failed() -> None:
    base = "https://apisandbox.dev.clover.com"
    respx.get(url__regex=rf"{base}/v3/merchants/MERCH1/orders.*").mock(
        return_value=httpx.Response(500, json={"message": "nope"})
    )
    conn = FakeConn()
    settings = _settings()
    clover = CloverClient(
        base_url=base,
        merchant_id="MERCH1",
        api_token="tokensecret",
        client=httpx.Client(),
    )
    try:
        with pytest.raises(RuntimeError, match="HTTP 500"):
            run_ingest(
                settings,
                conn=conn,  # type: ignore[arg-type]
                clover=clover,
                source_request_id="req-fail",
            )
    finally:
        clover.close()

    assert conn.finished
    _finished_at, status, rows_processed, error_message, _run_id = conn.finished[-1]
    assert status == "failed"
    assert rows_processed is None
    assert error_message is not None
    assert "tokensecret" not in error_message
    assert "HTTP 500" in error_message
    assert not conn.merges


def test_map_order_payload_is_copy() -> None:
    row = map_order(SAMPLE_ORDER, merchant_id="M", source_request_id="r")
    row["payload"]["id"] = "MUTATED"
    assert SAMPLE_ORDER["id"] == "ORD1"


def test_map_line_item_unit_qty_none() -> None:
    row = map_line_item(
        {"id": "L", "name": "x"},
        order_id="O",
        merchant_id="M",
        source_request_id="r",
    )
    assert row["unit_qty"] is None
    assert row["price_cents"] is None


def test_raw_loader_batches_and_dedups_in_merge() -> None:
    conn = FakeConn()
    base = extract_from_orders([SAMPLE_ORDER], merchant_id="M", source_request_id="r")[0][0]
    orders = [{**base, "clover_order_id": f"O{i}"} for i in range(250)]
    assert RawLoader(conn).upsert_all(orders, [], []) == 250  # type: ignore[arg-type]
    # 250 lignes → 3 INSERT multi-lignes (100 + 100 + 50)
    assert [len(rows) for _sql, rows in conn.staged] == [100, 100, 50]
    assert len(conn.merges) == 1
    assert "QUALIFY ROW_NUMBER() OVER" in conn.merges[0]
    assert "PARSE_JSON(payload_json)" in conn.merges[0]


def test_raw_loader_switches_to_file_and_copy_for_large_volumes(monkeypatch) -> None:
    monkeypatch.setattr("scripts.ingest_clover.BULK_LOAD_THRESHOLD", 100)
    conn = FakeConn()
    base = extract_from_orders([SAMPLE_ORDER], merchant_id="M", source_request_id="r")[0][0]
    orders = [{**base, "clover_order_id": f"O{i}"} for i in range(250)]

    assert RawLoader(conn).upsert_all(orders, [], []) == 250  # type: ignore[arg-type]

    statements = conn.statements()
    put = next(s for s in statements if s.startswith("PUT "))
    copy = next(s for s in statements if s.startswith("COPY INTO"))
    assert "@raw.%stg_raw_clover_orders" in put and "@raw.%stg_raw_clover_orders" in copy
    assert "MATCH_BY_COLUMN_NAME" in copy and "PURGE = TRUE" in copy
    assert statements.index(put) < statements.index(copy) < statements.index("BEGIN")
    assert not conn.staged  # aucun INSERT ligne à ligne
    assert len(conn.merges) == 1


def test_stage_file_holds_one_json_object_per_row(tmp_path) -> None:
    from datetime import datetime, timezone

    rows = [
        {"clover_order_id": "O1", "note": None, "created_time": datetime(2026, 10, 31, 15, 0, tzinfo=timezone.utc), "payload_json": '{"id":"O1"}'},
        {"clover_order_id": "O2", "note": "sans oignon", "created_time": None, "payload_json": "{}"},
    ]
    lines = write_stage_file(rows, tmp_path / "stage.json").read_text(encoding="utf-8").splitlines()

    assert [json.loads(line) for line in lines] == [
        {"clover_order_id": "O1", "created_time": "2026-10-31T15:00:00+00:00", "payload_json": '{"id":"O1"}'},
        {"clover_order_id": "O2", "note": "sans oignon", "payload_json": "{}"},
    ]


def test_raw_table_staging_is_schema_qualified() -> None:
    assert RAW_ORDERS.staging == "raw.stg_raw_clover_orders"
    assert RAW_ORDERS.create_staging_sql().startswith(
        "CREATE OR REPLACE TEMPORARY TABLE raw.stg_raw_clover_orders"
    )
