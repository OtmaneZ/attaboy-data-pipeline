-- =============================================================================
-- Attaboy — 000_bootstrap.sql (Snowflake)
-- =============================================================================
-- Infra Snowflake dédiée : warehouse, plafond de crédits, base, schémas,
-- rôles, utilisateur de service et privilèges.
--
-- EXÉCUTION (une fois, par un humain ayant ACCOUNTADMIN) :
--   Snowsight → Worksheet → coller ce fichier → Run All
--   ou : snow sql -f sql/000_bootstrap.sql
--
-- Idempotent (IF NOT EXISTS / GRANT rejouables).
-- Aucun secret ici : la clé publique RSA est posée à l'étape 6, à la main.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. Plafond de coûts (ACCOUNTADMIN requis pour les resource monitors)
-- ---------------------------------------------------------------------------
USE ROLE ACCOUNTADMIN;

CREATE RESOURCE MONITOR IF NOT EXISTS ATTABOY_RM
    WITH CREDIT_QUOTA = 10
    FREQUENCY = MONTHLY
    START_TIMESTAMP = IMMEDIATELY
    TRIGGERS
        ON 75 PERCENT DO NOTIFY
        ON 100 PERCENT DO SUSPEND
        ON 110 PERCENT DO SUSPEND_IMMEDIATE;

-- ---------------------------------------------------------------------------
-- 2. Warehouse + base + schémas (SYSADMIN = propriétaire des objets)
-- ---------------------------------------------------------------------------
USE ROLE SYSADMIN;

CREATE WAREHOUSE IF NOT EXISTS ATTABOY_WH
    WAREHOUSE_SIZE = XSMALL
    AUTO_SUSPEND = 60
    AUTO_RESUME = TRUE
    INITIALLY_SUSPENDED = TRUE
    COMMENT = 'Attaboy — ingest Clover + dbt. XS, suspend après 60 s.';

CREATE DATABASE IF NOT EXISTS ATTABOY_DW
    DATA_RETENTION_TIME_IN_DAYS = 1
    COMMENT = 'Data warehouse Attaboy (pizzeria). Clover POS + factures fournisseurs.';

CREATE SCHEMA IF NOT EXISTS ATTABOY_DW.RAW
    COMMENT = 'Couche brute non transformée (Clover, factures). MERGE uniquement, pas de logique métier.';
CREATE SCHEMA IF NOT EXISTS ATTABOY_DW.META
    COMMENT = 'Métadonnées opérationnelles du pipeline (runs, monitoring).';
CREATE SCHEMA IF NOT EXISTS ATTABOY_DW.ANALYTICS
    COMMENT = 'Modèles dbt (staging en vues, marts en tables).';

USE ROLE ACCOUNTADMIN;
ALTER WAREHOUSE ATTABOY_WH SET RESOURCE_MONITOR = ATTABOY_RM;

-- ---------------------------------------------------------------------------
-- 3. Rôles fonctionnels (rattachés à SYSADMIN, bonne pratique Snowflake)
-- ---------------------------------------------------------------------------
USE ROLE SECURITYADMIN;

CREATE ROLE IF NOT EXISTS ATTABOY_PIPELINE
    COMMENT = 'Écriture pipeline Attaboy (ingest, dbt). Limité à ATTABOY_DW.';
CREATE ROLE IF NOT EXISTS ATTABOY_READONLY
    COMMENT = 'Lecture seule Attaboy (Power BI, Snowsight, analyses). Aucun droit d''écriture.';

GRANT ROLE ATTABOY_PIPELINE TO ROLE SYSADMIN;
GRANT ROLE ATTABOY_READONLY TO ROLE SYSADMIN;

-- L'administrateur qui exécute ce script doit pouvoir faire USE ROLE ATTABOY_PIPELINE
-- pour créer les tables (001, 002) dont le pipeline sera propriétaire.
SET attaboy_admin_user = CURRENT_USER();
GRANT ROLE ATTABOY_PIPELINE TO USER IDENTIFIER($attaboy_admin_user);

-- ---------------------------------------------------------------------------
-- 4. Privilèges ATTABOY_PIPELINE
-- ---------------------------------------------------------------------------
GRANT USAGE, OPERATE ON WAREHOUSE ATTABOY_WH TO ROLE ATTABOY_PIPELINE;
GRANT USAGE ON DATABASE ATTABOY_DW TO ROLE ATTABOY_PIPELINE;

-- CREATE TABLE couvre aussi les tables temporaires de staging de l'ingest.
GRANT USAGE, CREATE TABLE, CREATE VIEW ON SCHEMA ATTABOY_DW.RAW TO ROLE ATTABOY_PIPELINE;
GRANT USAGE, CREATE TABLE, CREATE VIEW ON SCHEMA ATTABOY_DW.META TO ROLE ATTABOY_PIPELINE;
GRANT USAGE, CREATE TABLE, CREATE VIEW ON SCHEMA ATTABOY_DW.ANALYTICS TO ROLE ATTABOY_PIPELINE;

-- ---------------------------------------------------------------------------
-- 5. Privilèges ATTABOY_READONLY (objets existants + futurs, dont ceux de dbt)
-- ---------------------------------------------------------------------------
GRANT USAGE ON WAREHOUSE ATTABOY_WH TO ROLE ATTABOY_READONLY;
GRANT USAGE ON DATABASE ATTABOY_DW TO ROLE ATTABOY_READONLY;

GRANT USAGE ON SCHEMA ATTABOY_DW.RAW TO ROLE ATTABOY_READONLY;
GRANT USAGE ON SCHEMA ATTABOY_DW.META TO ROLE ATTABOY_READONLY;
GRANT USAGE ON SCHEMA ATTABOY_DW.ANALYTICS TO ROLE ATTABOY_READONLY;

GRANT SELECT ON ALL TABLES IN SCHEMA ATTABOY_DW.RAW TO ROLE ATTABOY_READONLY;
GRANT SELECT ON ALL TABLES IN SCHEMA ATTABOY_DW.META TO ROLE ATTABOY_READONLY;
GRANT SELECT ON ALL TABLES IN SCHEMA ATTABOY_DW.ANALYTICS TO ROLE ATTABOY_READONLY;
GRANT SELECT ON ALL VIEWS IN SCHEMA ATTABOY_DW.ANALYTICS TO ROLE ATTABOY_READONLY;

GRANT SELECT ON FUTURE TABLES IN SCHEMA ATTABOY_DW.RAW TO ROLE ATTABOY_READONLY;
GRANT SELECT ON FUTURE TABLES IN SCHEMA ATTABOY_DW.META TO ROLE ATTABOY_READONLY;
GRANT SELECT ON FUTURE TABLES IN SCHEMA ATTABOY_DW.ANALYTICS TO ROLE ATTABOY_READONLY;
GRANT SELECT ON FUTURE VIEWS IN SCHEMA ATTABOY_DW.ANALYTICS TO ROLE ATTABOY_READONLY;

-- ---------------------------------------------------------------------------
-- 6. Utilisateur de service (authentification par paire de clés uniquement)
-- ---------------------------------------------------------------------------
USE ROLE USERADMIN;

CREATE USER IF NOT EXISTS ATTABOY_PIPELINE_SVC
    TYPE = SERVICE
    DEFAULT_ROLE = ATTABOY_PIPELINE
    DEFAULT_WAREHOUSE = ATTABOY_WH
    DEFAULT_NAMESPACE = ATTABOY_DW.RAW
    COMMENT = 'Compte technique du pipeline Attaboy (systemd timer). Clé RSA, pas de mot de passe.';

ALTER USER ATTABOY_PIPELINE_SVC SET TIMEZONE = 'UTC';

USE ROLE SECURITYADMIN;
GRANT ROLE ATTABOY_PIPELINE TO USER ATTABOY_PIPELINE_SVC;

-- Étape manuelle (clé générée sur le serveur, cf. README) :
--   ALTER USER ATTABOY_PIPELINE_SVC SET RSA_PUBLIC_KEY = 'MIIBIjANBgkqh...';
--   DESC USER ATTABOY_PIPELINE_SVC;  -- vérifier RSA_PUBLIC_KEY_FP
