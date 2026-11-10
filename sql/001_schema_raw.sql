-- =============================================================================
-- Attaboy — 001_schema_raw.sql (Snowflake)
-- =============================================================================
-- Tables brutes Clover + factures fournisseurs.
--
-- Snowflake n'impose pas PRIMARY KEY / UNIQUE / FOREIGN KEY (seul NOT NULL l'est).
-- Les contraintes sont déclarées pour documenter le modèle et aider les outils
-- (Power BI, dbt docs) ; l'unicité réelle est garantie par le MERGE de l'ingest
-- et vérifiée par les tests dbt (unique / not_null sur les sources).
--
-- EXÉCUTION (après 000) :
--   snow sql -f sql/001_schema_raw.sql
-- =============================================================================

USE ROLE ATTABOY_PIPELINE;
USE WAREHOUSE ATTABOY_WH;
USE SCHEMA ATTABOY_DW.RAW;

-- ---------------------------------------------------------------------------
-- RAW_CLOVER_ORDERS
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_clover_orders (
    clover_order_id       VARCHAR        NOT NULL COMMENT 'Clover order.id — clé du MERGE.',
    merchant_id           VARCHAR        NOT NULL COMMENT 'Merchant ID Clover ayant fourni la commande.',
    created_time          TIMESTAMP_TZ            COMMENT 'Création Clover (epoch ms → TIMESTAMP_TZ UTC).',
    modified_time         TIMESTAMP_TZ            COMMENT 'Modification Clover — filtre incrémental.',
    client_created_time   TIMESTAMP_TZ            COMMENT 'clientCreatedTime Clover, si présent.',
    state                 VARCHAR                 COMMENT 'État Clover (open, locked, …).',
    currency              VARCHAR                 COMMENT 'Devise ISO (ex. CAD).',
    total_cents           NUMBER(38, 0)           COMMENT 'Total commande en centimes (entier Clover).',
    payment_state         VARCHAR                 COMMENT 'État de paiement Clover (paid, …).',
    title                 VARCHAR                 COMMENT 'Titre / libellé de la commande.',
    note                  VARCHAR                 COMMENT 'Note libre associée à la commande.',
    payload               VARIANT        NOT NULL COMMENT 'JSON intégral renvoyé par l''API (expand inclus) — source de vérité brute.',
    _ingested_at          TIMESTAMP_TZ   NOT NULL DEFAULT CURRENT_TIMESTAMP() COMMENT 'Horodatage du dernier MERGE.',
    _source_request_id    VARCHAR        NOT NULL COMMENT 'run_id de l''ingest (corrélation logs / META.PIPELINE_RUNS).',
    CONSTRAINT pk_raw_clover_orders PRIMARY KEY (clover_order_id)
)
COMMENT = 'Commandes Clover brutes (GET /v3/merchants/{mId}/orders). Une ligne = un order.id.';

-- ---------------------------------------------------------------------------
-- RAW_CLOVER_LINE_ITEMS
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_clover_line_items (
    clover_line_item_id   VARCHAR        NOT NULL COMMENT 'Clover lineItem.id — clé du MERGE.',
    clover_order_id       VARCHAR        NOT NULL COMMENT 'Référence RAW_CLOVER_ORDERS.clover_order_id.',
    merchant_id           VARCHAR        NOT NULL COMMENT 'Merchant ID (dénormalisé).',
    name                  VARCHAR                 COMMENT 'Libellé produit tel que renvoyé par Clover.',
    price_cents           NUMBER(38, 0)           COMMENT 'Prix en centimes.',
    unit_qty              NUMBER(18, 6)           COMMENT 'Quantité (unitQty Clover).',
    item_id               VARCHAR                 COMMENT 'Référence inventaire Clover item.id.',
    created_time          TIMESTAMP_TZ            COMMENT 'Création de la ligne Clover.',
    modified_time         TIMESTAMP_TZ            COMMENT 'Modification de la ligne Clover.',
    payload               VARIANT        NOT NULL COMMENT 'JSON intégral du lineItem.',
    _ingested_at          TIMESTAMP_TZ   NOT NULL DEFAULT CURRENT_TIMESTAMP() COMMENT 'Horodatage du dernier MERGE.',
    _source_request_id    VARCHAR        NOT NULL COMMENT 'run_id de l''ingest.',
    CONSTRAINT pk_raw_clover_line_items PRIMARY KEY (clover_line_item_id),
    CONSTRAINT fk_raw_clover_line_items_order
        FOREIGN KEY (clover_order_id) REFERENCES raw_clover_orders (clover_order_id)
)
COMMENT = 'Lignes de commande Clover brutes (expand=lineItems). Une ligne = un lineItem.id.';

-- ---------------------------------------------------------------------------
-- RAW_CLOVER_PAYMENTS
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_clover_payments (
    clover_payment_id     VARCHAR        NOT NULL COMMENT 'Clover payment.id — clé du MERGE.',
    clover_order_id       VARCHAR        NOT NULL COMMENT 'Référence RAW_CLOVER_ORDERS.clover_order_id.',
    merchant_id           VARCHAR        NOT NULL COMMENT 'Merchant ID (dénormalisé).',
    amount_cents          NUMBER(38, 0)           COMMENT 'Montant payé en centimes (négatif = remboursement).',
    tip_amount_cents      NUMBER(38, 0)           COMMENT 'Pourboire en centimes.',
    tax_amount_cents      NUMBER(38, 0)           COMMENT 'Taxes en centimes.',
    result                VARCHAR                 COMMENT 'Résultat Clover (SUCCESS, …).',
    tender_type           VARCHAR                 COMMENT 'Moyen de paiement extrait du payload.',
    created_time          TIMESTAMP_TZ            COMMENT 'Création du paiement Clover.',
    modified_time         TIMESTAMP_TZ            COMMENT 'Modification du paiement Clover.',
    payload               VARIANT        NOT NULL COMMENT 'JSON intégral du payment.',
    _ingested_at          TIMESTAMP_TZ   NOT NULL DEFAULT CURRENT_TIMESTAMP() COMMENT 'Horodatage du dernier MERGE.',
    _source_request_id    VARCHAR        NOT NULL COMMENT 'run_id de l''ingest.',
    CONSTRAINT pk_raw_clover_payments PRIMARY KEY (clover_payment_id),
    CONSTRAINT fk_raw_clover_payments_order
        FOREIGN KEY (clover_order_id) REFERENCES raw_clover_orders (clover_order_id)
)
COMMENT = 'Paiements Clover bruts (expand=payments). Une ligne = un payment.id.';

-- ---------------------------------------------------------------------------
-- RAW_FACTURES_LIGNES (Mission 4)
-- ---------------------------------------------------------------------------
-- Une ligne = une ligne produit d'une facture fournisseur (Saputo / Colabor).
-- Totaux facture dénormalisés sur chaque ligne (table raw unique, traçable par PDF).
-- Clé métier du MERGE : (fournisseur_slug, numero_facture, ligne_numero).
-- ligne_numero > 0 : contrôlé côté ingest (CHECK non supporté par Snowflake).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_factures_lignes (
    id                    NUMBER(38, 0)  AUTOINCREMENT START 1 INCREMENT 1 ORDER COMMENT 'Surrogate technique.',
    fournisseur           VARCHAR        NOT NULL COMMENT 'Nom fournisseur tel qu''extrait.',
    fournisseur_slug      VARCHAR        NOT NULL COMMENT 'Slug normalisé (minuscules, sans accents).',
    numero_facture        VARCHAR        NOT NULL COMMENT 'Numéro de facture fournisseur.',
    date_facture          DATE                    COMMENT 'Date de facture.',
    ligne_numero          INTEGER        NOT NULL COMMENT 'Rang de la ligne dans la facture (1-based).',
    sku                   VARCHAR                 COMMENT 'Code article / SKU.',
    description           VARCHAR                 COMMENT 'Libellé produit extrait.',
    quantite              NUMBER(18, 6)           COMMENT 'Quantité facturée.',
    unite                 VARCHAR                 COMMENT 'Unité de mesure (kg, cs, unité, …).',
    prix_unitaire         NUMBER(18, 6)           COMMENT 'Prix unitaire (CAD sauf indication contraire).',
    total_ligne           NUMBER(18, 6)           COMMENT 'Montant de la ligne — validé vs sous-total.',
    sous_total_facture    NUMBER(18, 6)           COMMENT 'Sous-total facture (dénormalisé).',
    taxes_facture         NUMBER(18, 6)           COMMENT 'Taxes facture (dénormalisé).',
    total_facture         NUMBER(18, 6)           COMMENT 'Total TTC facture (dénormalisé).',
    devise                VARCHAR        NOT NULL DEFAULT 'CAD' COMMENT 'Devise (défaut CAD).',
    extraction_payload    VARIANT        NOT NULL COMMENT 'JSON intégral du parseur, pour audit d''extraction.',
    _ingested_at          TIMESTAMP_TZ   NOT NULL DEFAULT CURRENT_TIMESTAMP() COMMENT 'Horodatage du dernier MERGE.',
    _source_file          VARCHAR        NOT NULL COMMENT 'Nom du PDF source (provenance uniquement).',
    CONSTRAINT pk_raw_factures_lignes PRIMARY KEY (id),
    CONSTRAINT uq_raw_factures_lignes_business_ligne
        UNIQUE (fournisseur_slug, numero_facture, ligne_numero)
)
COMMENT = 'Lignes de factures fournisseurs extraites des PDF. Chargées seulement si somme des lignes ≈ sous-total (±0,02 $).';
