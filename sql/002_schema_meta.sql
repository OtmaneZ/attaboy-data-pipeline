-- =============================================================================
-- Attaboy — 002_schema_meta.sql (Snowflake)
-- =============================================================================
-- Journal d'exécution obligatoire pour chaque script (ingest, dbt).
-- Sert au monitoring et au watermark incrémental Clover (début du dernier succès).
--
-- run_id = UUID généré côté Python (Snowflake n'a pas INSERT … RETURNING).
-- Valeurs de status (running | success | failed) garanties par l'application :
-- Snowflake ne supporte pas les contraintes CHECK.
--
-- EXÉCUTION (après 000) :
--   snow sql -f sql/002_schema_meta.sql
-- =============================================================================

USE ROLE ATTABOY_PIPELINE;
USE WAREHOUSE ATTABOY_WH;
USE SCHEMA ATTABOY_DW.META;

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id           VARCHAR(64)    NOT NULL COMMENT 'UUID du run, préfixé « demo- » pour la démo (= _source_request_id dans RAW).',
    pipeline_name    VARCHAR        NOT NULL COMMENT 'ingest_clover | ingest_factures | dbt_run.',
    started_at       TIMESTAMP_TZ   NOT NULL COMMENT 'Début d''exécution (UTC).',
    finished_at      TIMESTAMP_TZ            COMMENT 'Fin d''exécution — NULL tant que status = running.',
    status           VARCHAR(16)    NOT NULL COMMENT 'running | success | failed.',
    rows_processed   NUMBER(38, 0)           COMMENT 'Lignes traitées (sémantique propre à chaque pipeline).',
    error_message    VARCHAR(2000)           COMMENT 'Erreur actionnable si failed. Jamais de secrets.',
    CONSTRAINT pk_pipeline_runs PRIMARY KEY (run_id)
)
COMMENT = 'Historique de chaque exécution de pipeline, succès comme échec.';

-- Vue de supervision : dernier run par pipeline.
CREATE OR REPLACE VIEW v_pipeline_last_run
    COMMENT = 'Dernier run de chaque pipeline (supervision rapide).'
AS
SELECT *
FROM pipeline_runs
QUALIFY ROW_NUMBER() OVER (PARTITION BY pipeline_name ORDER BY started_at DESC) = 1;
