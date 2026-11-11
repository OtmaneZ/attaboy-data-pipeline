from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from scripts.demo_data import (
    DEMO_MERCHANT_ID,
    LOCAL_TZ,
    OPENING_HOUR,
    PIZZAS,
    DemoGenerator,
    closing_hour,
    load_orders,
    price_on,
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

    # Snowflake applique la longueur des VARCHAR (DuckDB et les faux non) :
    # le run_id doit tenir dans META.PIPELINE_RUNS.RUN_ID.
    ddl = (Path(__file__).parents[1] / "sql" / "002_schema_meta.sql").read_text(encoding="utf-8")
    max_len = int(re.search(r"run_id\s+VARCHAR\((\d+)\)", ddl).group(1))
    assert len(run_id) <= max_len


def test_closed_on_christmas_and_new_year() -> None:
    gen = DemoGenerator(seed=7)
    assert gen.orders_for_day(date(2025, 12, 25)) == []
    assert gen.orders_for_day(date(2026, 1, 1)) == []
    assert summarize(gen.generate(date(2025, 12, 24), date(2025, 12, 26)))["days"] == 2


def test_new_pizza_is_not_sold_before_its_launch() -> None:
    orders = DemoGenerator(seed=7).generate(date(2026, 5, 18), date(2026, 6, 14))
    first_sale = min(
        datetime.fromtimestamp(o["createdTime"] / 1000, tz=LOCAL_TZ).date()
        for o in orders
        for li in _elements(o, "lineItems")
        if li["item"]["id"] == "PIZ09"
    )
    assert first_sale >= date(2026, 6, 1)


def test_summer_is_busier_than_january() -> None:
    gen = DemoGenerator(seed=7)
    january = len(gen.generate(date(2026, 1, 12), date(2026, 1, 25)))
    july = len(gen.generate(date(2026, 7, 20), date(2026, 8, 2)))
    assert july > january * 1.3


def test_volume_stays_at_neighbourhood_scale() -> None:
    # Une pizzeria de quartier : quelques dizaines de commandes par jour, pas une chaîne.
    s = summarize(DemoGenerator(seed=7).generate(date(2026, 1, 5), date(2026, 3, 29)))
    assert 30 < s["orders_per_day"]["mean"] < 70


def test_extras_follow_their_popularity() -> None:
    counts: dict[str, int] = {}
    for o in DemoGenerator(seed=7).generate(START, END):
        for li in _elements(o, "lineItems"):
            names = [m["name"] for m in _elements(li, "modifications")]
            assert len(names) == len(set(names))  # jamais deux fois le même extra sur un article
            for name in names:
                counts[name] = counts.get(name, 0) + 1
    assert counts["Extra fromage"] > counts["Champignons"] > counts["Pâte sans gluten"]


def test_spring_price_increase_only_applies_to_pizzas_from_its_date() -> None:
    margherita = PIZZAS[0]
    assert price_on(margherita, date(2026, 3, 31)) == margherita.price_cents
    assert price_on(margherita, date(2026, 4, 1)) == margherita.price_cents + 100
    sold = {
        li["price"]
        for o in DemoGenerator(seed=7).generate(date(2026, 4, 1), date(2026, 4, 7))
        for li in _elements(o, "lineItems")
        if li["item"]["id"] == margherita.item_id
    }
    assert sold == {margherita.price_cents + 100}


def test_delivery_share_grows_from_one_year_to_the_next() -> None:
    def share(start: date, end: date) -> float:
        return summarize(DemoGenerator(seed=7).generate(start, end))["order_type_share"]["Livraison"]

    assert share(date(2026, 9, 1), date(2026, 10, 31)) > share(date(2024, 9, 1), date(2024, 10, 31))
