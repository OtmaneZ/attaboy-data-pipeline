from __future__ import annotations

from datetime import date, datetime

from scripts.demo_data import (
    DEMO_MERCHANT_ID,
    LOCAL_TZ,
    OPENING_HOUR,
    DemoGenerator,
    closing_hour,
    load_orders,
    summarize,
)
from scripts.ingest_clover import extract_from_orders
from tests.fakes import FakeConn

START = date(2026, 9, 7)  # un lundi
END = date(2026, 9, 20)  # deux semaines complètes


def _orders():
    return DemoGenerator(seed=7).generate(START, END)


def _elements(obj, key):
    return obj.get(key, {}).get("elements", [])


def test_deterministic_for_same_seed() -> None:
    assert DemoGenerator(seed=7).generate(START, END) == _orders()
    assert DemoGenerator(seed=8).generate(START, END) != _orders()


def test_ids_are_unique() -> None:
    orders = _orders()
    ids = [o["id"] for o in orders]
    ids += [li["id"] for o in orders for li in _elements(o, "lineItems")]
    ids += [p["id"] for o in orders for p in _elements(o, "payments")]
    assert len(ids) == len(set(ids))


def test_totals_are_consistent() -> None:
    for o in _orders():
        subtotal = sum(
            li["price"] + sum(m["amount"] for m in _elements(li, "modifications"))
            for li in _elements(o, "lineItems")
        )
        discount = -sum(d["amount"] for d in _elements(o, "discounts"))
        payment = _elements(o, "payments")[0]
        assert o["total"] == subtotal - discount + payment["taxAmount"]
        assert payment["amount"] == o["total"]
        assert payment["tipAmount"] >= 0
        if payment["tender"]["labelKey"] == "com.clover.tender.cash":
            assert payment["tipAmount"] == 0


def test_orders_within_opening_hours() -> None:
    for o in _orders():
        local = datetime.fromtimestamp(o["createdTime"] / 1000, tz=LOCAL_TZ)
        assert OPENING_HOUR <= local.hour < closing_hour(local.date())


def test_weekend_busier_than_monday() -> None:
    per_weekday: dict[int, int] = {}
    for o in _orders():
        wd = datetime.fromtimestamp(o["createdTime"] / 1000, tz=LOCAL_TZ).weekday()
        per_weekday[wd] = per_weekday.get(wd, 0) + 1
    assert per_weekday[5] > per_weekday[0]  # samedi > lundi


def test_refunds_match_payment() -> None:
    refunded = [o for o in _orders() if "refunds" in o]
    for o in refunded:
        refund = _elements(o, "refunds")[0]
        payment = _elements(o, "payments")[0]
        assert o["paymentState"] == "REFUNDED"
        assert refund["payment"]["id"] == payment["id"]
        assert refund["amount"] == payment["amount"]


def test_compatible_with_ingest_mapping() -> None:
    orders = _orders()
    o_rows, l_rows, p_rows = extract_from_orders(orders, merchant_id=DEMO_MERCHANT_ID, source_request_id="demo-x")
    assert len(o_rows) == len(orders)
    assert len(l_rows) == sum(len(_elements(o, "lineItems")) for o in orders)
    assert len(p_rows) == len(orders)
    assert all(r["created_time"] is not None for r in o_rows)
    assert {r["tender_type"] for r in p_rows} == {"Carte de crédit", "Débit", "Comptant"}


def test_summary_shape() -> None:
    s = summarize(_orders())
    assert s["days"] == 14
    assert s["orders"] > 0
    assert 20 < s["avg_ticket_incl_tax"] < 100


def test_load_orders_uses_merge_and_logs_run() -> None:
    conn = FakeConn()
    orders = DemoGenerator(seed=1).generate(START, START)
    rows = load_orders(orders, conn=conn)  # type: ignore[arg-type]

    assert rows == sum(1 + len(_elements(o, "lineItems")) + 1 for o in orders)
    assert len(conn.merges) == 3
    run_id, pipeline_name, _ = conn.started[0]
    assert run_id.startswith("demo-")
    assert pipeline_name == "load_demo"
    assert conn.finished[-1][1] == "success"
    staged_orders = conn.staged[0][1]
    assert all(r["merchant_id"] == DEMO_MERCHANT_ID for r in staged_orders)
