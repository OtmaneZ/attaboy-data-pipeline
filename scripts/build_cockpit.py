#!/usr/bin/env python3
"""Cockpit des ventes — génère une page HTML autonome à partir des tables rpt_*.

La page embarque ses données (JSON) : elle s'ouvre hors ligne, se partage comme un
fichier et ne consomme aucun crédit Snowflake quand on la consulte. Elle est
régénérée après chaque `dbt build`.

Usage :
    python -m scripts.build_cockpit                 # cible = ATTABOY_DBT_TARGET (local ou snowflake)
    python -m scripts.build_cockpit --out /chemin/index.html
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
COCKPIT_DIR = REPO_ROOT / "cockpit"
DBT_TARGET_DIR = REPO_ROOT / "dbt" / "target"
DEFAULT_OUT = COCKPIT_DIR / "dist" / "index.html"
DATA_PLACEHOLDER = "/*__COCKPIT_DATA__*/"

log = logging.getLogger("attaboy.build_cockpit")

# Une requête par bloc du cockpit. Uniquement des tables rpt_* (voir l'exposure dbt).
QUERIES: dict[str, str] = {
    "daily": """
        select date_day, iso_weekday, orders, items, gross_sales, discount_amount, refund_amount,
               net_sales, tax_amount, tip_amount, total_collected, discounted_orders, refunded_orders,
               net_sales_7d_avg
        from analytics.rpt_sales_daily
        order by date_day
    """,
    "channels": """
        select order_date, order_type, orders, net_sales, tip_amount
        from analytics.rpt_sales_by_channel_daily
        order by order_date, order_type
    """,
    "tenders": """
        select order_date, tender_type, orders, total_collected
        from analytics.rpt_sales_by_tender_daily
        order by order_date, tender_type
    """,
    "hourly": """
        select order_date, order_hour, orders, net_sales
        from analytics.rpt_sales_hourly
        order by order_date, order_hour
    """,
    "product_daily": """
        select order_date, product_id, quantity, net_sales, estimated_cost, lines_with_extras, extras_amount
        from analytics.rpt_product_daily
        order by order_date, product_id
    """,
    "products": """
        select product_id, max(product_name) as product_name, max(category) as category,
               min(order_date) as first_sold_date
        from analytics.rpt_product_daily
        group by product_id
        order by product_id
    """,
    "menu": """
        select product_id, product_name, category, quantity_sold, net_sales, estimated_cost,
               contribution_margin, unit_margin, category_unit_margin, mix_share, popularity_threshold,
               menu_class, recommended_action
        from analytics.rpt_menu_engineering
        order by category, quantity_sold desc
    """,
    "pairs": """
        select product_a_name, product_b_name, orders_together, support,
               confidence_a_to_b, confidence_b_to_a, lift
        from analytics.rpt_product_pairs
        order by lift desc
    """,
    "runs": """
        select pipeline_name, started_at, finished_at, status, rows_processed, duration_seconds
        from analytics.rpt_pipeline_runs
        order by started_at desc
        limit 10
    """,
}

TEST_GROUPS = (
    ("keys", "Clés : chaque ligne est unique et identifiée", {"unique", "not_null", "unique_combination_of_columns"}),
    ("relations", "Relations : aucune ligne orpheline entre les tables", {"relationships"}),
    ("values", "Valeurs : montants et libellés dans les bornes attendues", {"accepted_values", "accepted_range", "expression_is_true"}),
)


# ---------------------------------------------------------------------------
# Lecture de l'entrepôt (DuckDB local ou Snowflake) — même SQL des deux côtés
# ---------------------------------------------------------------------------


class Warehouse:
    def __init__(self, conn: Any, engine: str) -> None:
        self.conn = conn
        self.engine = engine

    @classmethod
    def open(cls, target: str) -> Warehouse:
        if target == "local":
            from scripts.local_warehouse import connect_local, local_db_path

            path = local_db_path()
            if not path.is_file():
                raise SystemExit(f"Entrepôt local introuvable : {path}. Lance d'abord `make demo`.")
            return cls(connect_local(path, read_only=True), "duckdb")
        if target == "snowflake":
            from scripts.snowflake_utils import SnowflakeSettings, connect, load_attaboy_env

            load_attaboy_env()
            return cls(connect(SnowflakeSettings.from_env(), query_tag="attaboy:cockpit"), "snowflake")
        raise SystemExit(f"Cible inconnue : {target!r} (attendu : local ou snowflake)")

    def table(self, sql: str) -> dict[str, list[Any]]:
        """Résultat compact : noms de colonnes + lignes, prêt pour le JSON."""
        cur = self.conn.cursor()
        try:
            cur.execute(sql)
            cols = [d[0].lower() for d in cur.description]
            rows = [[to_json(v) for v in row] for row in cur.fetchall()]
        finally:
            cur.close()
        return {"cols": cols, "rows": rows}

    def scalar(self, sql: str) -> Any:
        return self.table(sql)["rows"][0][0]

    def close(self) -> None:
        self.conn.close()


def to_json(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    return value


# ---------------------------------------------------------------------------
# Qualité : résultats du dernier `dbt build` (dbt/target)
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> Optional[dict[str, Any]]:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def collect_quality(target_dir: Path = DBT_TARGET_DIR) -> Optional[dict[str, Any]]:
    """Synthèse des tests et des modèles. None si dbt n'a pas encore tourné."""
    manifest = _read_json(target_dir / "manifest.json")
    run_results = _read_json(target_dir / "run_results.json")
    if not manifest or not run_results:
        return None
    if run_results.get("args", {}).get("which") not in ("build", "test"):
        log.warning("dbt/target ne contient pas le résultat d'un `dbt build` : bloc qualité ignoré")
        return None

    status_by_id = {r["unique_id"]: r["status"] for r in run_results.get("results", [])}
    nodes = manifest.get("nodes", {})

    def outcome(unique_id: str) -> Optional[str]:
        status = status_by_id.get(unique_id)
        if status is None:
            return None
        return {"pass": "pass", "warn": "warn"}.get(status, "fail")

    groups = {key: {"key": key, "label": label, "pass": 0, "warn": 0, "fail": 0} for key, label, _ in TEST_GROUPS}
    rules: list[dict[str, Any]] = []
    for unique_id, node in nodes.items():
        if node.get("resource_type") != "test":
            continue
        result = outcome(unique_id)
        if result is None:
            continue
        generic = (node.get("test_metadata") or {}).get("name")
        if generic is None:
            rules.append({"name": node["name"], "description": node.get("description") or "", "status": result})
            continue
        for key, _label, names in TEST_GROUPS:
            if generic in names:
                groups[key][result] += 1
                break

    unit_tests = []
    for unique_id, node in manifest.get("unit_tests", {}).items():
        result = outcome(unique_id)
        if result is not None:
            unit_tests.append(
                {"name": node["name"], "model": node.get("model"), "description": node.get("description") or "", "status": result}
            )

    totals = {"pass": 0, "warn": 0, "fail": 0}
    for item in [*groups.values()]:
        for k in totals:
            totals[k] += item[k]
    for item in [*rules, *unit_tests]:
        totals[item["status"]] += 1

    layers = {"staging": 0, "intermediate": 0, "marts": 0}
    marts = []
    for node in nodes.values():
        if node.get("resource_type") != "model" or node.get("package_name") != manifest["metadata"].get("project_name"):
            continue
        fqn = node.get("fqn", [])
        layer = fqn[1] if len(fqn) > 1 else ""
        if layer in layers:
            layers[layer] += 1
        if layer == "marts":
            marts.append(
                {
                    "name": node["name"],
                    "schema": node.get("schema"),
                    "description": " ".join((node.get("description") or "").split()),
                    "documented_columns": sum(1 for c in node.get("columns", {}).values() if c.get("description")),
                }
            )

    return {
        "dbt_version": manifest["metadata"].get("dbt_version"),
        "adapter": manifest["metadata"].get("adapter_type"),
        "invoked_at": run_results["metadata"].get("generated_at"),
        "elapsed_seconds": round(run_results.get("elapsed_time", 0), 1),
        "totals": totals,
        "groups": list(groups.values()),
        "rules": sorted(rules, key=lambda r: r["name"]),
        "unit_tests": sorted(unit_tests, key=lambda r: r["name"]),
        "layers": layers,
        "sources": sum(1 for s in manifest.get("sources", {}).values() if s.get("source_name") == "clover"),
        "marts": sorted(marts, key=lambda m: m["name"]),
    }


# ---------------------------------------------------------------------------
# Assemblage
# ---------------------------------------------------------------------------


def collect_data(warehouse: Warehouse, client: dict[str, Any], *, quality: Optional[dict[str, Any]]) -> dict[str, Any]:
    data: dict[str, Any] = {name: warehouse.table(sql) for name, sql in QUERIES.items()}
    if not data["daily"]["rows"]:
        raise SystemExit("analytics.rpt_sales_daily est vide : rien à afficher.")

    merchants = [r[0] for r in warehouse.table("select distinct merchant_id from analytics.fct_orders")["rows"]]
    if quality:
        for mart in quality["marts"]:
            mart["rows"] = warehouse.scalar(f"select count(*) from {mart['schema']}.{mart['name']}")
            del mart["schema"]

    days = data["daily"]["rows"]
    data["meta"] = {
        "client": {k: client[k] for k in ("name", "tagline", "currency", "locale")},
        "engine": warehouse.engine,
        # Tant que les données viennent du générateur, la page l'affiche en permanence.
        "is_demo": bool(merchants) and all(m in client.get("demo_merchant_ids", []) for m in merchants),
        "first_day": days[0][0],
        "last_day": days[-1][0],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    data["quality"] = quality
    return data


def render(template: str, data: dict[str, Any]) -> str:
    """Fragment HTML du cockpit, données incluses."""
    if DATA_PLACEHOLDER not in template:
        raise SystemExit(f"Le gabarit ne contient pas le repère {DATA_PLACEHOLDER}")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # Un JSON embarqué dans une balise <script> ne doit jamais pouvoir la refermer.
    payload = payload.replace("</", "<\\/")
    return template.replace(DATA_PLACEHOLDER, payload)


def standalone_page(fragment: str) -> str:
    """Enveloppe le fragment dans un document complet, lisible par double-clic."""
    return (
        '<!doctype html>\n<html lang="fr">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "</head>\n<body>\n" + fragment + "\n</body>\n</html>\n"
    )


def build(target: str, out: Path) -> Path:
    client = json.loads((COCKPIT_DIR / "client.json").read_text(encoding="utf-8"))
    template = (COCKPIT_DIR / "template.html").read_text(encoding="utf-8")
    warehouse = Warehouse.open(target)
    try:
        data = collect_data(warehouse, client, quality=collect_quality())
    finally:
        warehouse.close()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(standalone_page(render(template, data)), encoding="utf-8")
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    p = argparse.ArgumentParser(description="Génère le cockpit des ventes (page HTML autonome).")
    p.add_argument("--target", default=os.environ.get("ATTABOY_DBT_TARGET", "snowflake"), choices=("local", "snowflake"))
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = p.parse_args(argv)
    out = build(args.target, args.out)
    log.info("cockpit écrit : %s (%.0f Ko)", out, out.stat().st_size / 1024)
    return 0


if __name__ == "__main__":
    sys.exit(main())
