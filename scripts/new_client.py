#!/usr/bin/env python3
"""Prépare le dépôt d'un nouvel établissement à partir de celui-ci.

Un dépôt et une base par client (docs/decisions.md, décision 8) : on ne partage pas
le code à l'exécution, on en fait une copie renommée. Ce script copie les fichiers
versionnés, remplace le nom du client partout (objets Snowflake, variables
d'environnement, projet dbt, chemins du serveur), règle le cockpit, et laisse
un CONTEXT.md et un README à compléter.

Usage :
    python -m scripts.new_client --slug luigi --name "Chez Luigi" --tagline "Montréal" --out ../luigi

Il ne touche à rien d'autre que le dossier de destination, qui doit être vide ou absent.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]

# Le nom d'origine, sous ses trois formes : objets Snowflake et variables, identifiants, texte.
SOURCE_UPPER = "ATTABOY"
SOURCE_LOWER = "attaboy"
SOURCE_TITLE = "Attaboy"

# Propres à l'établissement d'origine : non copiés (captures) ou remplacés par un modèle à remplir.
SKIPPED_PREFIXES = ("docs/captures/",)
REWRITTEN = ("README.md", "CONTEXT.md")

SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,30}$")


@dataclass(frozen=True)
class ClientConfig:
    slug: str
    name: str
    tagline: str = ""
    timezone: Optional[str] = None
    currency: Optional[str] = None
    locale: Optional[str] = None

    def __post_init__(self) -> None:
        if not SLUG_PATTERN.match(self.slug):
            raise ValueError(
                f"slug invalide : {self.slug!r}. Minuscules, chiffres et _ seulement, en commençant par une lettre "
                "(il sert de nom d'objets Snowflake et de variables d'environnement)."
            )
        if self.slug == SOURCE_LOWER:
            raise ValueError("le slug doit différer de celui du dépôt d'origine.")
        if not self.name.strip():
            raise ValueError("le nom de l'établissement est vide.")


def tracked_files(root: Path) -> list[str]:
    """Fichiers versionnés du dépôt : ni secrets, ni données, ni fichiers générés."""
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True).stdout
    return sorted(p for p in out.decode("utf-8").split("\0") if p)


def rename(text: str, cfg: ClientConfig) -> str:
    return (
        text.replace(SOURCE_UPPER, cfg.slug.upper())
        .replace(SOURCE_LOWER, cfg.slug)
        .replace(SOURCE_TITLE, cfg.name)
    )


def _context_stub(cfg: ClientConfig) -> str:
    return f"""# Contexte métier — {cfg.name}

À compléter avant toute proposition d'architecture : c'est ce fichier qui donne l'échelle du projet.

## L'établissement

| | |
|---|---|
| Nom | {cfg.name} |
| Adresse | À COMPLÉTER |
| Type | À COMPLÉTER |
| Taille | À COMPLÉTER |
| Fuseau horaire | {cfg.timezone or "À COMPLÉTER (var local_timezone de dbt/dbt_project.yml)"} |
| Devise | {cfg.currency or "À COMPLÉTER"} |
| Caisse | À COMPLÉTER |

## Le projet

- Objectif : À COMPLÉTER.
- Les données de l'établissement ne sont jamais versionnées.

## Les trois étapes, toujours dans cet ordre

1. **Démo** sur données simulées, en local (DuckDB) : `make demo`.
2. **Projet réel** : mêmes modèles, sur Snowflake, avec les ventes de la caisse.
3. **Exploitation** : run quotidien, surveillance.

Ce qui dépend du client vit dans la configuration (voir [docs/nouveau-client.md](docs/nouveau-client.md)), jamais dans les modèles.

## Ordres de grandeur à garder en tête

- Volume : À COMPLÉTER (commandes par jour).
- Budget : À COMPLÉTER.
"""


def _readme_stub(cfg: ClientConfig) -> str:
    return f"""# {cfg.name} — de la caisse au tableau de bord

Pipeline de données et cockpit des ventes de **{cfg.name}** : les ventes de la caisse sont chargées dans Snowflake,
transformées et testées avec dbt, puis publiées dans une page HTML autonome.

## Démarrer

```bash
make install    # environnement Python + dbt
make demo       # données simulées → dbt build (modèles + tests) → cockpit/dist/index.html
```

## À adapter pour cet établissement

Suivre la liste de contrôle de [docs/nouveau-client.md](docs/nouveau-client.md), dans l'ordre. En bref :

1. Compléter [CONTEXT.md](CONTEXT.md).
2. Adapter le menu de la démo (`scripts/demo_data.py`) et les catalogues (`dbt/seeds/`).
3. Vérifier `cockpit/client.json` et les `vars` de `dbt/dbt_project.yml`.
4. Relire `docs/` : les décisions et les coûts ont été écrits pour un autre établissement.
5. Créer le compte Snowflake, jouer `sql/000` à `002`, remplir `.env`.

`make` affiche toutes les commandes disponibles.
"""


def _set_dbt_var(text: str, key: str, value: str) -> str:
    """Remplace la valeur d'une var de dbt_project.yml en gardant l'alignement et sans le commentaire d'origine."""
    pattern = re.compile(rf"^(\s+{re.escape(key)}:\s*)(\S+)(.*)$", re.MULTILINE)
    new_text, count = pattern.subn(lambda m: f"{m.group(1)}{value}", text, count=1)
    if count != 1:
        raise RuntimeError(f"var {key} introuvable dans dbt_project.yml")
    return new_text


def render(src: Path, files: Sequence[str], out: Path, cfg: ClientConfig) -> list[str]:
    """Écrit la copie renommée dans `out`. Retourne les fichiers écrits (chemins relatifs)."""
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"{out} existe et n'est pas vide : rien n'a été écrit.")
    written: list[str] = []
    for rel in files:
        if rel.startswith(SKIPPED_PREFIXES) or rel in REWRITTEN:
            continue
        data = (src / rel).read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            payload = data  # binaire : copié tel quel
        else:
            text = rename(text, cfg)
            if rel == "dbt/dbt_project.yml" and cfg.timezone:
                text = _set_dbt_var(text, "local_timezone", cfg.timezone)
            if rel == "cockpit/client.json":
                client = json.loads(text)
                client["name"] = cfg.name
                client["tagline"] = cfg.tagline
                if cfg.currency:
                    client["currency"] = cfg.currency
                if cfg.locale:
                    client["locale"] = cfg.locale
                text = json.dumps(client, ensure_ascii=False, indent=2) + "\n"
            payload = text.encode("utf-8")
        target = out / rename(rel, cfg)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        target.chmod((src / rel).stat().st_mode & 0o777)
        written.append(str(target.relative_to(out)))

    for rel, content in (("CONTEXT.md", _context_stub(cfg)), ("README.md", _readme_stub(cfg))):
        (out / rel).write_text(content, encoding="utf-8")
        written.append(rel)
    return sorted(written)


def leftovers(out: Path, cfg: ClientConfig) -> list[str]:
    """Fichiers de la copie qui mentionnent encore l'établissement d'origine."""
    if SOURCE_LOWER in cfg.name.lower():
        return []
    found = []
    for path in sorted(p for p in out.rglob("*") if p.is_file()):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if SOURCE_LOWER in text.lower():
            found.append(str(path.relative_to(out)))
    return found


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Prépare le dépôt d'un nouvel établissement à partir de celui-ci.")
    p.add_argument("--slug", required=True, help="identifiant court, ex. luigi → LUIGI_DW, LUIGI_SF_ACCOUNT, /opt/clients/luigi")
    p.add_argument("--name", required=True, help="nom affiché de l'établissement")
    p.add_argument("--tagline", default="", help="sous-titre du cockpit (ville, quartier)")
    p.add_argument("--timezone", help="fuseau horaire IANA, ex. America/Toronto, Europe/Paris")
    p.add_argument("--currency", help="devise ISO, ex. CAD, EUR")
    p.add_argument("--locale", help="langue et pays du cockpit, ex. fr-CA, fr-FR")
    p.add_argument("--out", type=Path, required=True, help="dossier de destination (vide ou absent)")
    args = p.parse_args(argv)

    try:
        cfg = ClientConfig(args.slug, args.name, args.tagline, args.timezone, args.currency, args.locale)
        out = args.out.resolve()
        written = render(REPO_ROOT, tracked_files(REPO_ROOT), out, cfg)
    except (ValueError, FileExistsError) as exc:
        raise SystemExit(f"Erreur : {exc}")

    remaining = leftovers(out, cfg)
    print(f"{len(written)} fichiers écrits dans {out}")
    if remaining:
        print("Mentions de l'établissement d'origine encore présentes :", ", ".join(remaining))
        return 1
    print("Suite : cd dans ce dossier, `git init`, `make install`, `make demo`, puis docs/nouveau-client.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
