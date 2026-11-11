-- =============================================================================
-- Attaboy — 100_visite_guidee.sql (Snowflake)
-- =============================================================================
-- Le tour de l'entrepôt en dix requêtes, à coller dans une feuille Snowsight.
-- Sert à trois choses : apprendre à interroger ses données (lecture seule),
-- vérifier un chargement, et illustrer le projet (chaque bloc donne un écran).
--
-- Rien ici ne modifie les données, sauf le bloc 10 (un clone, supprimé aussitôt).
-- Dans Snowsight, Ctrl + Entrée n'exécute que l'instruction sous le curseur :
-- sélectionner le bloc entier avant de lancer.
--
-- Blocs 1 à 7 : rôle ATTABOY_READONLY (celui du propriétaire).
-- Blocs 8 à 10 : rôles d'administration, à la fin.
-- =============================================================================

USE ROLE ATTABOY_READONLY;
USE WAREHOUSE ATTABOY_WH;
USE DATABASE ATTABOY_DW;

-- ---------------------------------------------------------------------------
-- 1. Ce que contient l'entrepôt
-- ---------------------------------------------------------------------------
-- Quatre schémas : RAW (le JSON de la caisse), STAGING (vues de préparation),
-- ANALYTICS (tables à interroger), META (journal du pipeline).
-- Les vues n'ont ni lignes ni taille : elles ne stockent rien, elles recalculent.
SELECT
    table_schema                    AS schema,
    table_name                      AS objet,
    table_type                      AS type,
    row_count                       AS lignes,
    ROUND(bytes / 1024 / 1024, 2)   AS mo
FROM information_schema.tables
WHERE table_schema <> 'INFORMATION_SCHEMA'
ORDER BY table_schema, table_name;

-- ---------------------------------------------------------------------------
-- 2. Le JSON brut de la caisse, lu comme des colonnes
-- ---------------------------------------------------------------------------
-- `payload` est de type VARIANT : on y descend avec « : » puis « . »,
-- et « ::type » convertit la valeur. Cliquer sur une cellule `payload`
-- affiche le JSON complet d'une commande.
SELECT
    clover_order_id                              AS commande,
    payload:orderType.label::string              AS type_commande,
    payload:total::number / 100                  AS total,
    payload:discounts.elements[0].name::string   AS rabais,
    payload
FROM raw.raw_clover_orders
WHERE payload:discounts IS NOT NULL
LIMIT 10;

-- ---------------------------------------------------------------------------
-- 3. Déplier un tableau JSON : une ligne par extra
-- ---------------------------------------------------------------------------
-- Une commande contient des articles, un article contient des extras.
-- LATERAL FLATTEN transforme chaque tableau en lignes : c'est ce que font
-- les modèles stg_clover__modifications, __discounts et __refunds.
SELECT
    o.clover_order_id               AS commande,
    li.value:name::string           AS article,
    m.value:name::string            AS extra,
    m.value:amount::number / 100    AS prix_extra
FROM raw.raw_clover_orders o,
    LATERAL FLATTEN(input => o.payload:lineItems.elements) li,
    LATERAL FLATTEN(input => li.value:modifications.elements) m
LIMIT 20;

-- ---------------------------------------------------------------------------
-- 4. L'heure de la caisse et l'heure du restaurant
-- ---------------------------------------------------------------------------
-- Clover horodate en UTC. Une commande de 22 h 57 à Québec porte la date du
-- lendemain en UTC : sans conversion, elle tomberait sur le mauvais jour.
SELECT
    created_time                                                        AS heure_utc,
    CONVERT_TIMEZONE('America/Toronto', created_time)::timestamp_ntz    AS heure_du_restaurant
FROM raw.raw_clover_orders
ORDER BY created_time DESC
LIMIT 5;

-- ---------------------------------------------------------------------------
-- 5. Les ventes par mois
-- ---------------------------------------------------------------------------
-- Après l'exécution, onglet « Chart » : type Bar, mois en abscisse,
-- ventes_nettes en ordonnée. La saison d'été saute aux yeux.
SELECT
    month_start                 AS mois,
    ROUND(SUM(net_sales))       AS ventes_nettes,
    SUM(orders)                 AS commandes,
    ROUND(SUM(net_sales) / NULLIF(SUM(orders), 0), 2) AS panier_moyen
FROM analytics.rpt_sales_daily
GROUP BY month_start
ORDER BY month_start;

-- ---------------------------------------------------------------------------
-- 6. Le classement de la carte
-- ---------------------------------------------------------------------------
-- Vedette, Valeur sûre, Énigme, Poids mort : popularité × marge, par catégorie.
SELECT
    product_name        AS produit,
    quantity_sold       AS vendus,
    unit_margin         AS marge_unitaire,
    menu_class          AS classement,
    recommended_action  AS piste
FROM analytics.rpt_menu_engineering
WHERE category = 'Pizzas'
ORDER BY quantity_sold DESC;

-- ---------------------------------------------------------------------------
-- 7. Le journal du pipeline
-- ---------------------------------------------------------------------------
-- Chaque chargement laisse une ligne : quand, combien de lignes, en combien
-- de secondes, et le message d'erreur s'il a échoué.
SELECT
    pipeline_name       AS pipeline,
    started_at          AS debut,
    status              AS statut,
    rows_processed      AS lignes,
    duration_seconds    AS secondes,
    ROUND(rows_processed / NULLIF(duration_seconds, 0)) AS lignes_par_seconde
FROM analytics.rpt_pipeline_runs
ORDER BY started_at;

-- =============================================================================
-- Administration (ACCOUNTADMIN)
-- =============================================================================

USE ROLE ACCOUNTADMIN;
USE WAREHOUSE ATTABOY_WH;
USE DATABASE ATTABOY_DW;

-- ---------------------------------------------------------------------------
-- 8. Qui a le droit de quoi, et combien ça coûte
-- ---------------------------------------------------------------------------
-- Le rôle du propriétaire : uniquement USAGE et SELECT, aucune écriture.
SHOW GRANTS TO ROLE ATTABOY_READONLY;

-- Le robot du pipeline : un utilisateur de type SERVICE, sans mot de passe
-- (connexion par paire de clés).
SHOW USERS LIKE 'ATTABOY_PIPELINE_SVC';

-- Le plafond de dépenses : 10 crédits par mois, suspension automatique à 100 %.
SHOW RESOURCE MONITORS LIKE 'ATTABOY_RM';

-- Crédits réellement consommés par jour (mise à jour avec quelques heures de retard).
SELECT
    TO_DATE(start_time)             AS jour,
    ROUND(SUM(credits_used), 3)     AS credits
FROM snowflake.account_usage.warehouse_metering_history
WHERE warehouse_name = 'ATTABOY_WH'
GROUP BY jour
ORDER BY jour;

-- ---------------------------------------------------------------------------
-- 9. Qui a fait tourner l'entrepôt
-- ---------------------------------------------------------------------------
-- Chaque composant marque ses requêtes (QUERY_TAG) : on sait ce qui vient
-- du chargement, de dbt ou de la génération du cockpit.
SELECT
    query_tag                                   AS composant,
    COUNT(*)                                    AS requetes,
    ROUND(SUM(total_elapsed_time) / 1000)       AS secondes
FROM TABLE(information_schema.query_history_by_warehouse(
    warehouse_name => 'ATTABOY_WH',
    result_limit => 10000
))
WHERE query_tag LIKE 'attaboy:%'
    AND execution_status = 'SUCCESS'
GROUP BY query_tag
ORDER BY requetes DESC;

-- ---------------------------------------------------------------------------
-- 10. Remonter le temps, puis cloner sans copier
-- ---------------------------------------------------------------------------
-- Time Travel : l'état d'une table il y a une heure (rétention : 1 jour).
-- Après un rechargement, l'écart entre les deux nombres montre ce qui a changé.
SELECT
    (SELECT COUNT(*) FROM raw.raw_clover_orders)                         AS commandes_maintenant,
    (SELECT COUNT(*) FROM raw.raw_clover_orders AT(OFFSET => -60 * 60))  AS commandes_il_y_a_une_heure;

-- Clone zéro-copie : un schéma d'essai complet, créé en une seconde, qui ne
-- prend aucune place tant qu'on n'y modifie rien. Utile pour essayer un
-- changement de modèle sans toucher aux tables que lit le cockpit.
USE ROLE SYSADMIN;
CREATE SCHEMA ATTABOY_DW.ANALYTICS_ESSAI CLONE ATTABOY_DW.ANALYTICS;
SELECT COUNT(*) AS commandes_dans_le_clone FROM ATTABOY_DW.ANALYTICS_ESSAI.fct_orders;
DROP SCHEMA ATTABOY_DW.ANALYTICS_ESSAI;
