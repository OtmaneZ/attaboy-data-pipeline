#!/usr/bin/env python3
"""Captures d'écran du cockpit et du graphe de dépendances dbt (README, portfolio).

Outil de développement : nécessite Playwright (requirements-dev.txt) et
`python -m playwright install chromium`.

Usage :
    python -m scripts.capture                       # cockpit → docs/captures/
    python -m scripts.capture --dbt-docs local/dbt_docs/static_index.html
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COCKPIT = REPO_ROOT / "cockpit" / "dist" / "index.html"
DEFAULT_OUT = REPO_ROOT / "docs" / "captures"

# (fichier, onglet, période en jours, thème, largeur, hauteur, page entière)
SHOTS = (
    ("cockpit-ventes.png", "ventes", 90, "light", 1440, 900, True),
    ("cockpit-ventes-12-mois.png", "ventes", 365, "light", 1440, 900, True),
    ("cockpit-carte.png", "carte", 90, "light", 1440, 900, True),
    ("cockpit-fiabilite.png", "fiabilite", None, "light", 1440, 900, True),
    ("cockpit-ventes-sombre.png", "ventes", 365, "dark", 1440, 900, True),
    ("cockpit-mobile.png", "ventes", 90, "light", 400, 860, False),
    # Formats réseaux : rapport 1,91:1 (publication LinkedIn) et 4:3 (portfolio Malt)
    ("social-linkedin.png", "ventes", 365, "light", 1600, 838, False),
    ("social-malt.png", "carte", 90, "light", 1440, 1080, False),
)


def capture_cockpit(browser, cockpit: Path, out_dir: Path) -> list[Path]:
    written = []
    for name, tab, days, theme, width, height, full_page in SHOTS:
        context = browser.new_context(
            viewport={"width": width, "height": height}, device_scale_factor=2, color_scheme=theme, locale="fr-CA"
        )
        page = context.new_page()
        page.goto(f"{cockpit.as_uri()}#{tab}")
        page.wait_for_selector("#view > *")
        page.evaluate("document.fonts.ready")
        if days is not None:
            page.click(f"#period-{days}")
        page.wait_for_timeout(400)
        target = out_dir / name
        page.screenshot(path=str(target), full_page=full_page)
        written.append(target)
        context.close()
    return written


def capture_lineage(browser, dbt_docs: Path, out_dir: Path) -> Path:
    """Graphe de dépendances complet, tel qu'affiché par la documentation dbt."""
    context = browser.new_context(viewport={"width": 1800, "height": 1000}, device_scale_factor=2)
    page = context.new_page()
    page.goto(f"{dbt_docs.as_uri()}#!/overview?g_v=1")
    page.wait_for_selector("canvas", timeout=30000)
    page.wait_for_timeout(2500)
    target = out_dir / "dbt-lineage.png"
    page.screenshot(path=str(target))
    context.close()
    return target


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Captures d'écran du cockpit et du lineage dbt.")
    p.add_argument("--cockpit", type=Path, default=DEFAULT_COCKPIT)
    p.add_argument("--dbt-docs", type=Path, help="static_index.html produit par `dbt docs generate --static`")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = p.parse_args(argv)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("Playwright manquant : pip install -r requirements-dev.txt && python -m playwright install chromium")
    if not args.cockpit.is_file():
        raise SystemExit(f"Cockpit introuvable : {args.cockpit}. Lance d'abord `make demo`.")

    args.out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        written = capture_cockpit(browser, args.cockpit.resolve(), args.out)
        if args.dbt_docs:
            written.append(capture_lineage(browser, args.dbt_docs.resolve(), args.out))
        browser.close()
    for path in written:
        print(path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
