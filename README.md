# Attaboy — pipeline data

Pipeline de données d'**Attaboy, pizzeria de quartier** (Québec, rue Saint-Jean) : les ventes de la caisse Clover sont chargées chaque jour dans Snowflake, puis transformées avec dbt en tables prêtes pour Power BI ou les dashboards Snowsight.

Contexte et ordres de grandeur : [CONTEXT.md](CONTEXT.md) · Coûts d'infrastructure : [docs/couts.md](docs/couts.md)

## Architecture

```
API Clover ──► scripts/ingest_clover.py ──► Snowflake ATTABOY_DW
               (incrémental, MERGE)         ├─ RAW        données brutes (JSON en VARIANT)
                                            ├─ META       journal des runs (PIPELINE_RUNS)
                                            └─ ANALYTICS  modèles dbt ──► Power BI / Snowsight
                                                          (stg_* en vues, fct_* en tables)    (rôle ATTABOY_READONLY)
```

- **Incrémental** : chaque run relit les commandes Clover modifiées depuis le début du dernier run réussi.
- **Idempotent** : chargement en tables temporaires puis `MERGE` dédoublonné dans une transaction. Relancer un run ne crée pas de doublon.
- **Sécurité** : compte de service Snowflake avec paire de clés RSA (sans mot de passe), rôles séparés écriture / lecture, secrets uniquement dans `.env` hors du repo.
- **Coûts maîtrisés** : warehouse XS en veille après 60 s, plafond de 10 crédits par mois.

## Contenu du repo

| Dossier | Rôle |
|---------|------|
| `sql/` | Provisioning Snowflake versionné : `000` infra + rôles, `001` tables RAW, `002` tables META, `999` suppression complète |
| `scripts/` | `ingest_clover.py` (ingest), `snowflake_utils.py` (connexion, `.env`, journal des runs) |
| `dbt/` | Modèles `staging` et `marts` (`fct_order_lines`, `fct_sales_daily`) + tests |
| `tests/` | Tests unitaires pytest (sans connexion réelle) |
| `docs/` | Documentation de passation |

## Mise en place

### 1. Snowflake (une fois, avec le rôle ACCOUNTADMIN)

```bash
# Paire de clés du compte de service, sur le serveur
install -d -m 700 /opt/clients/attaboy/keys && cd /opt/clients/attaboy/keys
openssl genrsa 2048 | openssl pkcs8 -topk8 -v2 aes-256-cbc -inform PEM -out snowflake_rsa_key.p8
openssl rsa -in snowflake_rsa_key.p8 -pubout -out snowflake_rsa_key.pub
chmod 600 snowflake_rsa_key.p8
```

Dans Snowsight (Worksheet), exécuter dans l'ordre :

1. `sql/000_bootstrap.sql`
2. `ALTER USER ATTABOY_PIPELINE_SVC SET RSA_PUBLIC_KEY = '<contenu de .pub sans les lignes BEGIN/END>';`
3. `sql/001_schema_raw.sql`, puis `sql/002_schema_meta.sql`

### 2. Serveur

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example /opt/clients/attaboy/.env   # puis remplir ; chmod 600
```

### 3. Lancer

```bash
set -a; source /opt/clients/attaboy/.env; set +a

.venv/bin/python -m scripts.ingest_clover          # Clover → RAW

export DBT_PROFILES_DIR=$PWD/dbt
cd dbt && ../.venv/bin/dbt debug && ../.venv/bin/dbt build   # modèles + tests
```

Tests unitaires : `.venv/bin/pytest -q`

### Données de démonstration

Les captures et la démo de ce repo utilisent des **données simulées** : `scripts/demo_data.py` génère des commandes fictives de pizzeria au format exact de l'API Clover (menu, affluence selon l'heure et le jour, extras, rabais, taxes TPS/TVQ, pourboires, remboursements). Aucune donnée réelle du restaurant n'apparaît dans ce repo.

```bash
.venv/bin/python -m scripts.demo_data --days 120          # résumé de contrôle, rien n'est chargé
.venv/bin/python -m scripts.demo_data --days 120 --load   # chargement dans RAW via le même MERGE que l'ingest
```

Les lignes simulées portent le `merchant_id` `DEMOPIZZERIA1` et un `run_id` préfixé `demo-`.

## Suivi

```sql
SELECT * FROM ATTABOY_DW.META.V_PIPELINE_LAST_RUN;   -- dernier run de chaque pipeline
```

## État

- [x] Ingest Clover → Snowflake
- [x] Modèles dbt ventes (lignes de commande, ventes par jour)
- [ ] Ingest des factures fournisseurs PDF (Saputo, Colabor) → coûts matières
- [ ] Orchestration quotidienne (systemd timer, 05:00 heure de l'Est) + alertes Healthchecks.io
- [ ] Utilisateur en lecture seule pour Power BI / Snowsight
- [ ] Passage au compte Snowflake du restaurant

## Réversibilité

`sql/999_teardown.sql` supprime tout ce que le projet a créé dans Snowflake (récupérable pendant 1 jour avec `UNDROP DATABASE`). Les données brutes peuvent être rechargées à tout moment depuis l'API Clover.
