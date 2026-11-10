# Contexte métier — Attaboy

À lire avant toute proposition d'architecture : **Attaboy n'est pas une entreprise, c'est une pizzeria de quartier.**

## Le restaurant

| | |
|---|---|
| Nom | Attaboy, pizzeria de quartier |
| Adresse | 597, rue Saint-Jean, Québec (QC) G1R 1P7 — quartier Saint-Jean-Baptiste |
| Type | Pizzeria indépendante, un seul établissement, pizzas cuites sur pierre, options véganes |
| Taille | Petite équipe, propriétaire-exploitant |
| Fuseau horaire | Heure de l'Est (`America/Toronto` dans le code, même fuseau que Québec) |
| Devise | CAD |
| Caisse | Clover (un seul marchand) |
| Fournisseurs suivis | Saputo, Colabor (factures PDF) |

Une fiche en ligne mentionne aussi le 1086, avenue Cartier : probablement une ancienne adresse ou une erreur d'annuaire, à confirmer avec le propriétaire.

## Le projet

- Objectif : donner au restaurant des chiffres utiles (ventes du jour, coûts fournisseurs).
- Le propriétaire s'intéresse à la data : il doit pouvoir comprendre, lire et interroger ses données. Privilégier la clarté et la documentation.
- Le propriétaire a accepté que le code soit public. Les données du restaurant, elles, ne sont jamais versionnées.

## Les trois étapes, toujours dans cet ordre

1. **Démo** sur données simulées, en local (DuckDB) : `make demo`. C'est ce que montrent les captures.
2. **Projet réel** pour Attaboy : mêmes modèles, sur Snowflake, avec les ventes de la caisse.
3. **Autres établissements** : le dépôt sert de base, un dépôt et une base par client.

Tout ajout doit rester valable aux trois étapes : ce qui dépend du client vit dans la configuration (voir [docs/nouveau-client.md](docs/nouveau-client.md)), jamais dans les modèles.

## Ordres de grandeur à garder en tête

- Volume : quelques dizaines à quelques centaines de commandes par jour. Un an de données tient largement dans une seule table Snowflake.
- Budget : celui d'un petit restaurant. Warehouse Snowflake XS, plafond de 10 crédits par mois, un run par jour.
- Une seule personne pour opérer le pipeline.

## Ce qu'il ne faut PAS proposer

Multi-tenant, multi-régions, streaming temps réel (Kafka, Snowpipe Streaming), SSO d'entreprise, data mesh, orchestrateur lourd (Airflow, Dagster) ou toute brique sans bénéfice concret à cette échelle. Un batch quotidien via systemd, dbt et quelques tables bien testées suffisent.
