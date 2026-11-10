-- =============================================================================
-- Attaboy — 999_teardown.sql (Snowflake)
-- =============================================================================
-- Réversibilité : supprime TOUT ce que 000–002 ont créé.
-- DESTRUCTIF. Ne jamais lancer en routine. Exporter les données avant si besoin.
-- La base reste récupérable pendant DATA_RETENTION_TIME_IN_DAYS (1 jour) :
--   UNDROP DATABASE ATTABOY_DW;
-- =============================================================================

USE ROLE ACCOUNTADMIN;

DROP USER IF EXISTS ATTABOY_PIPELINE_SVC;
DROP DATABASE IF EXISTS ATTABOY_DW;
DROP WAREHOUSE IF EXISTS ATTABOY_WH;
DROP RESOURCE MONITOR IF EXISTS ATTABOY_RM;
DROP ROLE IF EXISTS ATTABOY_READONLY;
DROP ROLE IF EXISTS ATTABOY_PIPELINE;
