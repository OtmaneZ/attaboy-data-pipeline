#!/usr/bin/env python3
"""Données de démonstration — commandes FICTIVES au format de l'API Clover.

Simule l'activité d'une pizzeria de quartier : menu, horaires, affluence selon
l'heure, le jour et la saison, événements locaux, tempêtes de neige, extras,
rabais, taxes du Québec, pourboires, remboursements.
Aucune donnée réelle. Toutes les lignes portent le merchant_id DEMO_MERCHANT_ID
et un run_id préfixé « demo- » pour rester identifiables dans Snowflake.

Usage :
    python -m scripts.demo_data --days 120                 # résumé, rien n'est chargé
    python -m scripts.demo_data --days 120 --out demo.json # export JSON
    python -m scripts.demo_data --days 120 --load          # chargement dans RAW (Snowflake)
    python -m scripts.demo_data --days 365 --local         # chargement dans l'entrepôt local (DuckDB)
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import statistics
import sys
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Optional, Sequence
from zoneinfo import ZoneInfo

PIPELINE_NAME = "load_demo"
DEMO_MERCHANT_ID = "DEMOPIZZERIA1"
LOCAL_TZ = ZoneInfo("America/Toronto")
TAX_RATE = Decimal("0.14975")  # TPS 5 % + TVQ 9,975 %
CURRENCY = "CAD"
ID_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ0123456789"

log = logging.getLogger("attaboy.demo_data")


# ---------------------------------------------------------------------------
# Hypothèses (pizzeria de quartier) — à recalibrer avec le propriétaire
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MenuItem:
    item_id: str
    name: str
    price_cents: int
    weight: float  # popularité relative dans sa catégorie
    available_from: Optional[date] = None  # None = à la carte depuis toujours


PIZZAS = (
    MenuItem("PIZ01", "Pizza margherita", 1600, 3.0),
    MenuItem("PIZ02", "Pizza pepperoni", 1800, 3.5),
    MenuItem("PIZ03", "Pizza toute garnie", 2000, 2.0),
    MenuItem("PIZ04", "Pizza végétarienne", 1900, 1.5),
    MenuItem("PIZ05", "Pizza quatre fromages", 1950, 1.5),
    MenuItem("PIZ06", "Pizza prosciutto roquette", 2200, 1.2),
    MenuItem("PIZ07", "Pizza végane", 1900, 1.0),
    MenuItem("PIZ08", "Pizza du mois", 2100, 0.8),
    MenuItem("PIZ09", "Pizza miel piquant", 2150, 2.2, available_from=date(2026, 6, 1)),
)
ENTREES = (
    MenuItem("ENT01", "Pain à l'ail", 650, 2.0),
    MenuItem("ENT02", "Salade César", 900, 1.5),
    MenuItem("ENT03", "Arancini", 800, 1.0),
)
DRINKS = (
    MenuItem("BOI01", "Boisson gazeuse", 300, 3.0),
    MenuItem("BOI02", "Eau pétillante", 350, 1.0),
    MenuItem("BOI03", "Bière locale", 750, 2.0),
    MenuItem("BOI04", "Verre de vin", 950, 1.0),
)
DESSERTS = (
    MenuItem("DES01", "Tiramisu", 700, 1.5),
    MenuItem("DES02", "Cannoli", 500, 1.0),
)
ALCOHOL_IDS = {"BOI03", "BOI04"}
# (pizza, boisson) → multiplicateur de popularité de la boisson quand la pizza est dans la commande.
DRINK_AFFINITY = {
    ("PIZ06", "BOI04"): 4.0,  # prosciutto roquette + verre de vin
    ("PIZ05", "BOI04"): 2.0,
    ("PIZ02", "BOI03"): 1.8,  # pepperoni + bière
    ("PIZ03", "BOI03"): 1.8,
    ("PIZ09", "BOI03"): 2.2,
    ("PIZ07", "BOI02"): 2.5,  # végane + eau pétillante
    ("PIZ04", "BOI02"): 2.0,
}
EXTRAS = (
    ("MOD01", "Extra fromage", 250, 3.0),
    ("MOD02", "Champignons", 200, 2.0),
    ("MOD03", "Piments forts", 100, 1.5),
    ("MOD04", "Pâte sans gluten", 300, 0.7),
)
ORDER_TYPES = ("Sur place", "À emporter", "Livraison")
# Part de chaque type de commande selon le contexte (même ordre que ORDER_TYPES).
ORDER_TYPE_WEIGHTS = {
    "normal": (0.45, 0.40, 0.15),
    "ete": (0.52, 0.37, 0.11),  # terrasse et touristes
    "hiver": (0.38, 0.40, 0.22),  # on commande plus de chez soi
    "tempete": (0.15, 0.35, 0.50),
    "match": (0.20, 0.45, 0.35),  # soirée de match : on mange devant la télé
}
TENDERS = (
    ("Carte de crédit", "com.clover.tender.credit_card", 0.55),
    ("Débit", "com.clover.tender.debit_card", 0.30),
    ("Comptant", "com.clover.tender.cash", 0.15),
)
TIP_PROBABILITY = {"Sur place": 0.85, "Livraison": 0.60, "À emporter": 0.35}
# Une quarantaine de places et un comptoir à emporter : une cinquantaine de commandes par jour,
# soit environ 700 000 $ de ventes par an. Au-delà, ce n'est plus une pizzeria de quartier.
BASE_ORDERS_PER_DAY = 46
WEEKDAY_FACTOR = {0: 0.70, 1: 0.75, 2: 0.85, 3: 1.00, 4: 1.35, 5: 1.45, 6: 1.05}
HOUR_WEIGHTS = {11: 4, 12: 10, 13: 7, 14: 3, 15: 2, 16: 3, 17: 8, 18: 11, 19: 9, 20: 5, 21: 3, 22: 2}
OPENING_HOUR = 11
# Saisonnalité : rue Saint-Jean, forte affluence touristique l'été, creux en janvier.
MONTH_FACTOR = {1: 0.80, 2: 0.90, 3: 0.88, 4: 0.94, 5: 1.02, 6: 1.12, 7: 1.25, 8: 1.20, 9: 1.05, 10: 0.98, 11: 0.90, 12: 1.00}
ANNUAL_GROWTH = 0.06  # le restaurant gagne de la clientèle d'une année à l'autre
GROWTH_REFERENCE = date(2026, 1, 1)
DELIVERY_GROWTH = 0.30  # la livraison progresse plus vite que la salle
# Nouvelle carte de printemps : (date d'effet, préfixe des produits, hausse en cents).
PRICE_INCREASES = ((date(2026, 4, 1), "PIZ", 100),)
EXTRA_PROBABILITY = 0.22
CLOSED_DAYS = {(12, 25), (1, 1)}  # (mois, jour)
SNOWSTORM_RATE = 0.07  # part des jours de décembre à mars
SNOWSTORM_FACTOR = 0.60
WINTER_MONTHS = (12, 1, 2, 3)
SUMMER_MONTHS = (6, 7, 8)
REFUND_RATE = 0.01
LUNCH_PROMO_RATE = 0.06  # promo midi en semaine
STAFF_DISCOUNT_RATE = 0.02


def closing_hour(day: date) -> int:
    """21 h du dimanche au mercredi, 23 h du jeudi au samedi."""
    return 23 if day.weekday() in (3, 4, 5) else 21


def is_closed(day: date) -> bool:
    return (day.month, day.day) in CLOSED_DAYS


def is_match_night(day: date) -> bool:
    """Deuxième dimanche de février : grande soirée de football à la télé."""
    return day.month == 2 and day.weekday() == 6 and 8 <= day.day <= 14


def event_factor(day: date) -> float:
    """Événements locaux récurrents (dates approximatives, données simulées)."""
    md = (day.month, day.day)
    if is_match_night(day):
        return 1.55
    if md == (6, 24):  # Fête nationale
        return 1.40
    if (7, 9) <= md <= (7, 19):  # grand festival de musique d'été
        return 1.25
    if (2, 6) <= md <= (2, 15):  # carnaval d'hiver
        return 1.15
    if md == (12, 31):
        return 1.30
    return 1.0


def growth_factor(day: date) -> float:
    return 1 + ANNUAL_GROWTH * (day - GROWTH_REFERENCE).days / 365


def delivery_trend(day: date) -> float:
    """Poids relatif de la livraison : il augmente d'une année à l'autre."""
    return max(0.5, 1 + DELIVERY_GROWTH * (day - GROWTH_REFERENCE).days / 365)


def price_on(item: MenuItem, day: date) -> int:
    """Prix de vente du produit ce jour-là, hausses de prix comprises."""
    return item.price_cents + sum(
        delta for since, prefix, delta in PRICE_INCREASES if day >= since and item.item_id.startswith(prefix)
    )


def cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def to_ms(dt: datetime) -> int:
    return int(dt.astimezone(timezone.utc).timestamp() * 1000)


# ---------------------------------------------------------------------------
# Générateur
# ---------------------------------------------------------------------------


class DemoGenerator:
    """Déterministe pour une graine donnée."""

    def __init__(self, seed: int = 42) -> None:
        self.rng = random.Random(seed)

    def _id(self) -> str:
        return "".join(self.rng.choice(ID_ALPHABET) for _ in range(13))

    def _pick(self, items: Sequence[MenuItem], day: Optional[date] = None) -> MenuItem:
        if day is not None:
            items = [i for i in items if i.available_from is None or i.available_from <= day]
        return self.rng.choices(items, weights=[i.weight for i in items])[0]

    def _pick_drink(self, pizza_ids: set[str], dine_in: bool) -> MenuItem:
        """La boisson dépend de la pizza et du lieu : c'est ce qui crée des associations à analyser."""
        weights = []
        for drink in DRINKS:
            w = drink.weight
            for pizza_id in sorted(pizza_ids):
                w *= DRINK_AFFINITY.get((pizza_id, drink.item_id), 1.0)
            if not dine_in and drink.item_id in ALCOHOL_IDS:
                w *= 0.35
            weights.append(w)
        return self.rng.choices(DRINKS, weights=weights)[0]

    def _pick_extras(self) -> list[tuple[str, str, int, float]]:
        """Un ou deux extras différents, tirés selon leur popularité (l'extra fromage domine)."""
        n = self.rng.choices([1, 2], weights=[80, 20])[0]
        pool = list(EXTRAS)
        picked = []
        for _ in range(n):
            extra = self.rng.choices(pool, weights=[weight for *_, weight in pool])[0]
            pool.remove(extra)
            picked.append(extra)
        return picked

    def _line(self, item: MenuItem, created_ms: int, day: date, with_extras: bool = False) -> dict[str, Any]:
        line: dict[str, Any] = {
            "id": self._id(),
            "name": item.name,
            "price": price_on(item, day),
            "item": {"id": item.item_id},
            "createdTime": created_ms,
            "modifiedTime": created_ms,
        }
        if with_extras and self.rng.random() < EXTRA_PROBABILITY:
            line["modifications"] = {
                "elements": [
                    {"id": self._id(), "name": name, "amount": amount, "modifier": {"id": mod_id}}
                    for mod_id, name, amount, _w in self._pick_extras()
                ]
            }
        return line

    def _order_times(self, day: date, n: int) -> list[datetime]:
        hours = [h for h in HOUR_WEIGHTS if OPENING_HOUR <= h < closing_hour(day)]
        weights = [HOUR_WEIGHTS[h] for h in hours]
        times = []
        for _ in range(n):
            hour = self.rng.choices(hours, weights=weights)[0]
            local = datetime.combine(day, time(hour, self.rng.randrange(60), self.rng.randrange(60)))
            times.append(local.replace(tzinfo=LOCAL_TZ))
        return sorted(times)

    def _day_context(self, day: date) -> str:
        """Contexte du jour : il décide de la répartition sur place / emporter / livraison."""
        if is_match_night(day):
            return "match"
        if day.month in WINTER_MONTHS:
            return "tempete" if self.rng.random() < SNOWSTORM_RATE else "hiver"
        return "ete" if day.month in SUMMER_MONTHS else "normal"

    def orders_for_day(self, day: date) -> list[dict[str, Any]]:
        if is_closed(day):
            return []
        context = self._day_context(day)
        expected = (
            BASE_ORDERS_PER_DAY
            * WEEKDAY_FACTOR[day.weekday()]
            * MONTH_FACTOR[day.month]
            * growth_factor(day)
            * event_factor(day)
            * (SNOWSTORM_FACTOR if context == "tempete" else 1.0)
        )
        n = max(1, round(expected * self.rng.uniform(0.85, 1.15)))
        return [
            self.order(created, seq, context=context)
            for seq, created in enumerate(self._order_times(day, n), start=1)
        ]

    def order(self, created_local: datetime, seq: int, *, context: str = "normal") -> dict[str, Any]:
        created_ms = to_ms(created_local)
        day = created_local.date()
        on_site, takeout, delivery = ORDER_TYPE_WEIGHTS[context]
        order_type = self.rng.choices(ORDER_TYPES, weights=(on_site, takeout, delivery * delivery_trend(day)))[0]

        lines: list[dict[str, Any]] = []
        n_pizzas = self.rng.choices([1, 2, 3, 4], weights=[50, 30, 15, 5])[0]
        for _ in range(n_pizzas):
            lines.append(self._line(self._pick(PIZZAS, day), created_ms, day, with_extras=True))
        dine_in = order_type == "Sur place"
        pizza_ids = {line["item"]["id"] for line in lines}
        if self.rng.random() < (0.38 if dine_in else 0.24):
            lines.append(self._line(self._pick(ENTREES), created_ms, day))
        for _ in range(n_pizzas):
            if self.rng.random() < (0.62 if dine_in else 0.40):
                lines.append(self._line(self._pick_drink(pizza_ids, dine_in), created_ms, day))
        if self.rng.random() < (0.24 if dine_in else 0.08):
            lines.append(self._line(self._pick(DESSERTS), created_ms, day))

        subtotal = sum(
            line["price"] + sum(m["amount"] for m in line.get("modifications", {}).get("elements", []))
            for line in lines
        )

        discounts: list[dict[str, Any]] = []
        is_weekday_lunch = created_local.weekday() < 5 and created_local.hour < 14
        roll = self.rng.random()
        if roll < STAFF_DISCOUNT_RATE:
            discounts.append(("Rabais employé", 20))
        elif is_weekday_lunch and roll < STAFF_DISCOUNT_RATE + LUNCH_PROMO_RATE:
            discounts.append(("Promo midi", 10))
        discount_elements = []
        discount_total = 0
        for name, pct in discounts:
            amount = cents(Decimal(subtotal) * pct / 100)
            discount_total += amount
            discount_elements.append({"id": self._id(), "name": name, "percentage": pct, "amount": -amount})

        taxable = subtotal - discount_total
        tax = cents(Decimal(taxable) * TAX_RATE)
        total = taxable + tax

        tender_label, tender_key, _ = self.rng.choices(TENDERS, weights=[w for *_, w in TENDERS])[0]
        tip = 0
        if tender_key != "com.clover.tender.cash" and self.rng.random() < TIP_PROBABILITY[order_type]:
            tip = cents(Decimal(taxable) * Decimal(self.rng.choice([10, 12, 15, 15, 18, 20])) / 100)

        if order_type == "Sur place":
            paid_at = created_local + timedelta(minutes=self.rng.randint(35, 75))
        else:
            paid_at = created_local + timedelta(minutes=self.rng.randint(0, 2))
        paid_ms = to_ms(paid_at)

        order_id = self._id()
        payment_id = self._id()
        order: dict[str, Any] = {
            "id": order_id,
            "currency": CURRENCY,
            "total": total,
            "state": "locked",
            "paymentState": "PAID",
            "title": self._title(order_type, seq),
            "note": None,
            "orderType": {"id": order_type.upper().replace(" ", "_"), "label": order_type},
            "createdTime": created_ms,
            "clientCreatedTime": created_ms,
            "modifiedTime": paid_ms,
            "lineItems": {"elements": lines},
            "payments": {
                "elements": [
                    {
                        "id": payment_id,
                        "order": {"id": order_id},
                        "amount": total,
                        "tipAmount": tip,
                        "taxAmount": tax,
                        "result": "SUCCESS",
                        "tender": {"label": tender_label, "labelKey": tender_key},
                        "createdTime": paid_ms,
                        "modifiedTime": paid_ms,
                    }
                ]
            },
        }
        if discount_elements:
            order["discounts"] = {"elements": discount_elements}

        if self.rng.random() < REFUND_RATE:
            refunded_at = paid_at + timedelta(minutes=self.rng.randint(5, 90))
            refunded_ms = to_ms(refunded_at)
            order["paymentState"] = "REFUNDED"
            order["modifiedTime"] = refunded_ms
            order["refunds"] = {
                "elements": [
                    {
                        "id": self._id(),
                        "payment": {"id": payment_id},
                        "amount": total,
                        "taxAmount": tax,
                        "tipAmount": tip,
                        "createdTime": refunded_ms,
                    }
                ]
            }
        return order

    def _title(self, order_type: str, seq: int) -> str:
        if order_type == "Sur place":
            return f"Table {self.rng.randint(1, 12)}"
        if order_type == "À emporter":
            return f"Emporter #{seq}"
        return f"Livraison #{seq}"

    def generate(self, start: date, end: date) -> list[dict[str, Any]]:
        """Commandes du jour `start` au jour `end` inclus."""
        if end < start:
            raise ValueError("end doit être >= start")
        orders: list[dict[str, Any]] = []
        day = start
        while day <= end:
            orders.extend(self.orders_for_day(day))
            day += timedelta(days=1)
        return orders


# ---------------------------------------------------------------------------
# Résumé (contrôle de vraisemblance avant chargement)
# ---------------------------------------------------------------------------


def summarize(orders: Sequence[dict[str, Any]]) -> dict[str, Any]:
    per_day: Counter[date] = Counter()
    revenue_per_day: Counter[date] = Counter()
    tenders: Counter[str] = Counter()
    types: Counter[str] = Counter()
    for o in orders:
        day = datetime.fromtimestamp(o["createdTime"] / 1000, tz=LOCAL_TZ).date()
        per_day[day] += 1
        revenue_per_day[day] += o["total"]
        tenders[o["payments"]["elements"][0]["tender"]["label"]] += 1
        types[o["orderType"]["label"]] += 1
    n = len(orders)
    return {
        "days": len(per_day),
        "orders": n,
        "line_items": sum(len(o["lineItems"]["elements"]) for o in orders),
        "orders_per_day": {
            "mean": round(statistics.mean(per_day.values()), 1),
            "min": min(per_day.values()),
            "max": max(per_day.values()),
        },
        "avg_ticket_incl_tax": round(sum(o["total"] for o in orders) / n / 100, 2),
        "revenue_per_day_incl_tax": round(statistics.mean(revenue_per_day.values()) / 100, 2),
        "refunds": sum(1 for o in orders if "refunds" in o),
        "with_discount": sum(1 for o in orders if "discounts" in o),
        "tender_share": {k: round(v / n, 3) for k, v in tenders.most_common()},
        "order_type_share": {k: round(v / n, 3) for k, v in types.most_common()},
    }


# ---------------------------------------------------------------------------
# Chargement Snowflake (même code que l'ingest : mapping + MERGE)
# ---------------------------------------------------------------------------


def load_orders(orders: Sequence[dict[str, Any]], *, conn: Any = None) -> int:
    from scripts.ingest_clover import RawLoader, extract_from_orders
    from scripts.snowflake_utils import (
        PipelineRunStore,
        SnowflakeSettings,
        connect,
        load_attaboy_env,
        sanitize_error,
    )

    run_id = f"demo-{uuid.uuid4()}"
    owns_conn = conn is None
    settings: Optional[SnowflakeSettings] = None
    store: Optional[PipelineRunStore] = None
    started = False
    try:
        if conn is None:
            load_attaboy_env()
            settings = SnowflakeSettings.from_env()
            conn = connect(settings, query_tag=f"attaboy:{PIPELINE_NAME}")
        store = PipelineRunStore(conn, PIPELINE_NAME)
        store.start_run(run_id, datetime.now(timezone.utc))
        started = True
        order_rows, line_rows, payment_rows = extract_from_orders(
            orders, merchant_id=DEMO_MERCHANT_ID, source_request_id=run_id
        )
        rows = RawLoader(conn).upsert_all(order_rows, line_rows, payment_rows)
        store.finish_run(run_id, status="success", rows_processed=rows, error_message=None)
        return rows
    except Exception as exc:
        if store is not None and started:
            secrets = settings.secrets() if settings else ()
            store.finish_run(
                run_id, status="failed", rows_processed=None, error_message=sanitize_error(exc, *secrets)
            )
        raise
    finally:
        if owns_conn and conn is not None:
            conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Commandes fictives de pizzeria au format Clover (démo).")
    p.add_argument("--days", type=int, default=120, help="Nombre de jours jusqu'à --end inclus (défaut 120)")
    p.add_argument("--end", type=date.fromisoformat, help="Dernier jour (AAAA-MM-JJ). Défaut : hier")
    p.add_argument("--seed", type=int, default=42, help="Graine aléatoire (défaut 42)")
    p.add_argument("--out", type=Path, help="Écrit les commandes en JSON dans ce fichier")
    p.add_argument("--load", action="store_true", help="Charge les commandes dans Snowflake (RAW)")
    p.add_argument(
        "--local",
        action="store_true",
        help="Charge les commandes dans l'entrepôt local DuckDB (démo sans compte Snowflake)",
    )
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    args = parse_args(argv)
    if args.days < 1:
        raise SystemExit("--days doit être >= 1")
    end = args.end or (datetime.now(LOCAL_TZ).date() - timedelta(days=1))
    start = end - timedelta(days=args.days - 1)

    orders = DemoGenerator(seed=args.seed).generate(start, end)
    summary = {"start": start.isoformat(), "end": end.isoformat(), **summarize(orders)}
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.out:
        args.out.write_text(json.dumps(orders, ensure_ascii=False), encoding="utf-8")
        log.info("écrit %s commandes dans %s", len(orders), args.out)
    if args.load:
        rows = load_orders(orders)
        log.info("chargé %s lignes dans RAW (merchant_id=%s)", rows, DEMO_MERCHANT_ID)
    if args.local:
        from scripts.local_warehouse import load_demo_orders

        path, rows = load_demo_orders(orders, merchant_id=DEMO_MERCHANT_ID)
        log.info("chargé %s lignes dans l'entrepôt local %s", rows, path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
