# Reprendre ce projet pour un autre établissement

Le projet suit trois étapes, toujours dans le même ordre :

| Étape | Données | Moteur | Qui paie |
|---|---|---|---|
| 1. Démo | Simulées (`scripts/demo_data.py`) | DuckDB local | Personne |
| 2. Mise au point | Simulées ou sandbox de la caisse | Snowflake, compte du consultant | Le consultant |
| 3. Exploitation | Réelles | Snowflake, compte du client | Le client |

Passer d'une étape à l'autre ne change aucun modèle : seuls la cible dbt (`ATTABOY_DBT_TARGET`) et le fichier `.env` changent.

## Ce qui est propre à un client

Pour un nouvel établissement, on copie le dépôt (un dépôt et une base par client, voir la décision 8 dans [decisions.md](decisions.md)) et on adapte uniquement ceci :

| Quoi | Où |
|---|---|
| Nom, slogan, devise, langue du cockpit ; catégorie mise en avant dans l'onglet Carte (`focus_category`, facultatif : par défaut celle qui vend le plus) | `cockpit/client.json` |
| Fuseau horaire, heure de début de la journée de vente (établissement ouvert après minuit), fenêtre d'analyse de la carte | `vars` dans `dbt/dbt_project.yml` |
| Catégories et coûts des produits | `dbt/seeds/menu_catalog.csv` |
| Noms des objets Snowflake (`ATTABOY_DW`, `ATTABOY_WH`, rôles) | `sql/*.sql`, valeurs par défaut de `scripts/snowflake_utils.py` et `dbt/profiles.yml` |
| Identifiants de la caisse et du compte Snowflake | `.env` (jamais versionné) |
| Menu, horaires et affluence de la démo | constantes en tête de `scripts/demo_data.py` |
| Contexte métier et ordres de grandeur | `CONTEXT.md` |

## Ce qui ne change pas

- Le chargement idempotent (`MERGE`) et le journal des exécutions.
- Les couches dbt et leurs tests : `staging` → `intermediate` → `marts`.
- Les tables `rpt_*` et le cockpit, tant que la caisse est Clover.
- Le Makefile, la CI, la démo locale.

## Si la caisse n'est pas Clover

Seule la première couche est à réécrire : un script d'ingest qui remplit les tables `RAW`, et les modèles `stg_*` qui en lisent le JSON. À partir de `int_orders__amounts`, tout le reste (définition des ventes, marts, cockpit) s'applique tel quel si le staging expose les mêmes colonnes.

## Liste de contrôle

1. Copier le dépôt, renommer les objets Snowflake dans `sql/`.
2. Adapter `demo_data.py` au menu du client, lancer `make demo`, montrer le cockpit sur données simulées.
3. Recueillir les besoins sur cette base concrète, ajuster les modèles.
4. Créer le compte Snowflake du client, jouer `sql/000` à `002`, remplir `.env`.
5. Premier chargement réel, `dbt build`, rapprochement des totaux avec les rapports de la caisse.
6. Planifier `make daily` (timer systemd) et la surveillance.
