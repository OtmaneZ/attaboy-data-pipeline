# Décisions d'architecture

Chaque choix est dimensionné pour une pizzeria de quartier (voir [CONTEXT.md](../CONTEXT.md)) : quelques dizaines à quelques centaines de commandes par jour, une seule personne pour opérer le pipeline, un budget de petit restaurant.

## 1. Snowflake pour le projet, DuckDB pour la démo et la CI

**Décision.** Les mêmes modèles dbt tournent sur deux cibles : `snowflake` (l'entrepôt du restaurant) et `local` (un fichier DuckDB).

**Pourquoi.** Développer et tester sur Snowflake consomme des crédits et demande un compte. Avec la cible locale, n'importe qui clone le repo et voit le projet tourner en une minute ; la CI exécute le vrai `dbt build` à chaque push sans secret ni coût.

**Prix à payer.** Six macros (`dbt/macros/cross_db.sql`) isolent les différences de syntaxe : fuseau horaire, lecture du JSON, jour de la semaine. Les modèles eux-mêmes restent du SQL lisible, sans condition par moteur.

## 2. Le JSON brut est conservé, puis déplié dans dbt

**Décision.** L'ingest garde la réponse complète de l'API Clover dans une colonne `payload`. Les extras, rabais et remboursements sont dépliés dans les modèles de staging (`LATERAL FLATTEN` sur Snowflake).

**Pourquoi.** Si un besoin apparaît plus tard (un champ ignoré au départ), l'historique est déjà là : on modifie un modèle SQL, on ne recharge rien depuis la caisse.

## 3. Des tables reconstruites entièrement, pas de modèles incrémentaux

**Décision.** Tous les marts sont en `table`, recalculés à chaque exécution.

**Pourquoi.** Un an de ventes représente environ 18 000 commandes et 55 000 articles. La reconstruction complète prend quelques secondes ; l'incrémental ajouterait des cas limites (commandes modifiées, remboursements tardifs) sans rien faire gagner. À reconsidérer si une table dépasse quelques dizaines de millions de lignes.

## 4. Une seule définition des ventes, dans un seul modèle

**Décision.** `int_orders__amounts` calcule tous les montants d'une commande ; tous les marts en dérivent.

- Vente brute = articles + extras, hors taxes.
- Vente nette = vente brute − rabais − remboursements, hors taxes et hors pourboires.
- Un remboursement est rattaché à la date de la commande d'origine.

**À valider sur les données réelles.** Les rapports Clover rattachent un remboursement à sa propre date. Si l'écart gêne le rapprochement avec la caisse, la règle se change à un seul endroit.

## 5. Rabais et remboursements répartis au prorata sur les articles

**Décision.** Clover applique les rabais à la commande entière. Pour analyser les produits, `fct_order_lines` répartit la vente nette de la commande sur ses articles, au prorata de leur prix.

**Garde-fou.** Un test vérifie que la somme des articles redonne la vente nette de la commande, à 2 cents près.

## 6. Un cockpit HTML autonome plutôt qu'un outil de BI en ligne

**Décision.** Après chaque `dbt build`, `scripts/build_cockpit.py` génère une page HTML qui embarque ses données.

**Pourquoi.** Sur Snowflake, on paie le temps où l'entrepôt est allumé. Un tableau de bord connecté en direct le rallume à chaque consultation ; une page générée une fois par jour se consulte gratuitement, hors ligne, sur un téléphone. Les tables `rpt_*` restent ouvertes à Power BI ou Snowsight pour qui veut explorer.

**Limite.** Les chiffres datent du dernier run (un par jour). C'est le rythme auquel le propriétaire les regarde.

## 7. Le catalogue du menu est un fichier tenu à la main

**Décision.** `dbt/seeds/menu_catalog.csv` donne la catégorie et le coût matière estimé de chaque produit.

**Pourquoi.** L'analyse de la carte (popularité × marge) a besoin d'un coût par produit. En attendant l'ingest des factures fournisseurs, un fichier de 20 lignes versionné suffit, et le propriétaire peut le relire. Un produit absent du fichier apparaît « Non classé » et un test le signale.

## 8. Un dépôt et une base par client, jamais de multi-tenant

**Décision.** Chaque établissement a son dépôt, sa base, son `.env`. Les données simulées ne partagent jamais une base avec des données réelles.

**Garde-fou.** Le test `assert_single_merchant` échoue si une base contient plus d'un marchand Clover. Voir [nouveau-client.md](nouveau-client.md).

## 9. Les champs libres restent dans RAW

**Décision.** Le titre et la note d'une commande, qui peuvent contenir un nom ou un numéro de téléphone, ne sortent pas du schéma `RAW`. Les modèles n'exposent que des identifiants, des montants et des horodatages.

**Pourquoi.** Loi 25 (Québec) : moins un renseignement personnel circule, moins il y a à protéger. Un inventaire complet des payloads est prévu dès les premières données réelles.
