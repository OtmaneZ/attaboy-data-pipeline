# Attaboy — commandes du projet. `make` sans argument affiche l'aide.
SHELL := /bin/bash
VENV ?= .venv
PY := $(abspath $(VENV))/bin/python
DBT := $(abspath $(VENV))/bin/dbt

# Fenêtre fixe pour la démo : mêmes chiffres et mêmes captures à chaque exécution.
DEMO_END ?= 2026-10-31
DEMO_DAYS ?= 730

export DBT_PROFILES_DIR := $(abspath dbt)
export ATTABOY_LOCAL_DB ?= $(abspath local/attaboy_demo.duckdb)
ATTABOY_HOME ?= /opt/clients/attaboy

.DEFAULT_GOAL := help
.PHONY: help install test demo demo-data demo-build demo-cockpit docs captures daily clean

help: ## Affiche cette aide
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  make %-14s %s\n", $$1, $$2}'

install: ## Crée l'environnement Python et installe les dépendances (dont dbt_utils)
	python3 -m venv $(VENV)
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -r requirements-dev.txt
	cd dbt && ATTABOY_DBT_TARGET=local $(DBT) deps

test: ## Tests unitaires Python (aucune connexion requise)
	$(PY) -m pytest -q

demo: demo-data demo-build demo-cockpit ## Démo complète en local : données simulées → dbt → cockpit (aucun compte requis)
	@echo "Cockpit prêt : cockpit/dist/index.html"

demo-data: ## Génère deux ans de commandes simulées dans l'entrepôt local (DuckDB)
	$(PY) -m scripts.demo_data --end $(DEMO_END) --days $(DEMO_DAYS) --local

demo-build: ## Construit et teste les modèles dbt sur l'entrepôt local
	cd dbt && ATTABOY_DBT_TARGET=local $(DBT) build

demo-cockpit: ## Génère le cockpit à partir de l'entrepôt local
	ATTABOY_DBT_TARGET=local $(PY) -m scripts.build_cockpit

docs: ## Documentation dbt en un seul fichier (local/dbt_docs/static_index.html)
	cd dbt && ATTABOY_DBT_TARGET=local $(DBT) docs generate --static --target-path ../local/dbt_docs

captures: docs ## Captures d'écran du cockpit et du graphe dbt (docs/captures/)
	$(PY) -m scripts.capture --dbt-docs local/dbt_docs/static_index.html

# Fraîcheur : signale un ingest qui réussit sans rien charger depuis plus de 36 h. Elle n'arrête pas
# le run : un restaurant fermé quelques jours doit garder son cockpit. Un ingest en échec, lui, arrête tout.
daily: ## Run quotidien sur Snowflake : ingest Clover → fraîcheur → dbt → cockpit (lit $(ATTABOY_HOME)/.env)
	set -a; source $(ATTABOY_HOME)/.env; set +a; \
	export ATTABOY_DBT_TARGET=snowflake; \
	$(PY) -m scripts.ingest_clover \
	&& (cd dbt && ($(DBT) source freshness || echo "ATTENTION : aucune vente chargée récemment (voir ci-dessus)")) \
	&& (cd dbt && $(DBT) build) \
	&& $(PY) -m scripts.build_cockpit --out $(ATTABOY_HOME)/exports/cockpit.html

clean: ## Supprime l'entrepôt local et les fichiers générés
	rm -rf local cockpit/dist dbt/target dbt/logs
