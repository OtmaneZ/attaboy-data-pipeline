from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from scripts.build_cockpit import DATA_PLACEHOLDER, collect_quality, render, standalone_page, to_json


def test_to_json_converts_warehouse_types() -> None:
    assert to_json(Decimal("12.50")) == 12.5
    assert to_json(date(2026, 10, 31)) == "2026-10-31"
    assert to_json(datetime(2026, 10, 31, 15, 0, tzinfo=timezone.utc)) == "2026-10-31T15:00:00+00:00"
    assert to_json(datetime(2026, 10, 31, 15, 0)) == "2026-10-31T15:00:00+00:00"
    assert to_json("Pizza") == "Pizza"
    assert to_json(None) is None


def test_render_embeds_data_and_cannot_close_the_script_tag() -> None:
    template = f'<script type="application/json">{DATA_PLACEHOLDER}</script>'
    html = render(template, {"name": "</script><script>alert(1)</script>", "n": 1})

    assert html.count("</script>") == 1
    payload = html[len('<script type="application/json">') : -len("</script>")]
    assert json.loads(payload)["name"] == "</script><script>alert(1)</script>"


def test_render_requires_the_placeholder() -> None:
    with pytest.raises(SystemExit):
        render("<p>rien</p>", {})


def test_standalone_page_is_a_full_document() -> None:
    page = standalone_page("<title>Cockpit</title>")
    assert page.startswith("<!doctype html>")
    assert '<html lang="fr">' in page and "<title>Cockpit</title>" in page


def _write(path, payload) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_collect_quality_summarises_dbt_artifacts(tmp_path) -> None:
    test = lambda name, generic=None, description="": {  # noqa: E731
        "resource_type": "test",
        "name": name,
        "description": description,
        "test_metadata": {"name": generic} if generic else None,
    }
    model = lambda name, layer: {  # noqa: E731
        "resource_type": "model",
        "package_name": "attaboy",
        "name": name,
        "schema": "analytics",
        "fqn": ["attaboy", layer, name],
        "description": "Une\n  description.",
        "columns": {"a": {"description": "doc"}, "b": {"description": ""}},
    }
    _write(
        tmp_path / "manifest.json",
        {
            "metadata": {"project_name": "attaboy", "dbt_version": "1.10.0", "adapter_type": "duckdb"},
            "nodes": {
                "test.unique": test("unique_x", "unique"),
                "test.rel": test("rel_x", "relationships"),
                "test.range": test("range_x", "accepted_range"),
                "test.rule": test("assert_rule", description="Une règle métier."),
                "test.not_run": test("skipped", "not_null"),
                "model.stg": model("stg_x", "staging"),
                "model.fct": model("fct_x", "marts"),
            },
            "unit_tests": {"unit.a": {"name": "calc", "model": "fct_x", "description": "Un calcul."}},
            "sources": {"s1": {"source_name": "clover"}, "s2": {"source_name": "meta"}},
        },
    )
    _write(
        tmp_path / "run_results.json",
        {
            "metadata": {"generated_at": "2026-11-10T15:00:00Z"},
            "args": {"which": "build"},
            "elapsed_time": 4.26,
            "results": [
                {"unique_id": "test.unique", "status": "pass"},
                {"unique_id": "test.rel", "status": "warn"},
                {"unique_id": "test.range", "status": "fail"},
                {"unique_id": "test.rule", "status": "pass"},
                {"unique_id": "unit.a", "status": "pass"},
            ],
        },
    )

    quality = collect_quality(tmp_path)

    assert quality is not None
    assert quality["totals"] == {"pass": 3, "warn": 1, "fail": 1}
    assert {g["key"]: (g["pass"], g["warn"], g["fail"]) for g in quality["groups"]} == {
        "keys": (1, 0, 0),
        "relations": (0, 1, 0),
        "values": (0, 0, 1),
    }
    assert quality["rules"] == [{"name": "assert_rule", "description": "Une règle métier.", "status": "pass"}]
    assert quality["unit_tests"][0]["name"] == "calc"
    assert quality["layers"] == {"staging": 1, "intermediate": 0, "marts": 1}
    assert quality["sources"] == 1
    assert quality["marts"] == [
        {"name": "fct_x", "schema": "analytics", "description": "Une description.", "documented_columns": 1}
    ]


def test_collect_quality_ignores_missing_or_unrelated_artifacts(tmp_path) -> None:
    assert collect_quality(tmp_path) is None
    _write(tmp_path / "manifest.json", {"metadata": {}, "nodes": {}})
    _write(tmp_path / "run_results.json", {"metadata": {}, "args": {"which": "docs"}, "results": []})
    assert collect_quality(tmp_path) is None
