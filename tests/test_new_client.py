"""Copie renommée du dépôt pour un nouvel établissement."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import new_client
from scripts.new_client import ClientConfig, leftovers, render, rename, tracked_files

CFG = ClientConfig(slug="luigi", name="Chez Luigi", tagline="Montréal", timezone="Europe/Paris", currency="EUR", locale="fr-FR")


@pytest.fixture(scope="module")
def rendered(tmp_path_factory) -> Path:
    try:
        files = tracked_files(new_client.REPO_ROOT)
    except (subprocess.CalledProcessError, FileNotFoundError):
        files = []
    if not files:
        pytest.skip("la liste des fichiers vient de git : à lancer dans un dépôt git avec des fichiers suivis")
    out = tmp_path_factory.mktemp("client") / "luigi"
    render(new_client.REPO_ROOT, files, out, CFG)
    return out


def test_rename_covers_the_three_spellings():
    text = "ATTABOY_DW, /opt/clients/attaboy, cockpit d'Attaboy"
    assert rename(text, CFG) == "LUIGI_DW, /opt/clients/luigi, cockpit d'Chez Luigi"


def test_no_mention_of_the_original_client_remains(rendered: Path):
    assert leftovers(rendered, CFG) == []


def test_snowflake_objects_and_env_vars_are_renamed(rendered: Path):
    bootstrap = (rendered / "sql" / "000_bootstrap.sql").read_text()
    assert "LUIGI_DW" in bootstrap and "LUIGI_PIPELINE_SVC" in bootstrap
    env = (rendered / ".env.example").read_text()
    assert "LUIGI_SF_ACCOUNT=" in env and "/opt/clients/luigi" in env
    profile = (rendered / "dbt" / "profiles.yml").read_text()
    assert profile.startswith("#") and "\nluigi:\n" in profile


def test_dbt_project_and_cockpit_are_configured(rendered: Path):
    project = (rendered / "dbt" / "dbt_project.yml").read_text()
    assert "name: luigi" in project and "profile: luigi" in project
    assert "local_timezone: Europe/Paris" in project
    assert "America/Toronto" not in project
    client = json.loads((rendered / "cockpit" / "client.json").read_text())
    assert (client["name"], client["tagline"], client["currency"], client["locale"]) == (
        "Chez Luigi",
        "Montréal",
        "EUR",
        "fr-FR",
    )
    assert client["demo_merchant_ids"]  # la démo doit continuer à tourner


def test_client_specific_files_are_replaced_not_copied(rendered: Path):
    assert not (rendered / "docs" / "captures").exists()
    context = (rendered / "CONTEXT.md").read_text()
    assert "Chez Luigi" in context and "À COMPLÉTER" in context and "Saint-Jean" not in context
    assert "docs/nouveau-client.md" in (rendered / "README.md").read_text()


def test_code_is_copied_with_its_tests(rendered: Path):
    for rel in ("Makefile", "scripts/ingest_clover.py", "dbt/models/marts/core/fct_orders.sql", "tests/test_ingest_clover.py"):
        assert (rendered / rel).is_file(), rel


def test_refuses_a_non_empty_destination(tmp_path: Path):
    (tmp_path / "deja-la.txt").write_text("x")
    with pytest.raises(FileExistsError):
        render(new_client.REPO_ROOT, ["Makefile"], tmp_path, CFG)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["deja-la.txt"]


@pytest.mark.parametrize("slug", ["Luigi", "chez-luigi", "1luigi", "l", "attaboy", ""])
def test_rejects_slugs_that_cannot_name_snowflake_objects(slug: str):
    with pytest.raises(ValueError):
        ClientConfig(slug=slug, name="Chez Luigi")
