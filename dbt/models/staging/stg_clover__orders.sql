-- Une ligne par commande. Les champs libres (titre, note) restent dans RAW :
-- ils peuvent contenir des renseignements personnels.
with source as (
    select * from {{ source('clover', 'raw_clover_orders') }}
)

select
    clover_order_id as order_id,
    merchant_id,
    created_time as created_at_utc,
    {{ local_ts('created_time') }} as created_at_local,
    modified_time as modified_at_utc,
    lower(state) as order_state,
    upper(payment_state) as payment_state,
    currency,
    coalesce({{ json_text('payload', 'orderType.label') }}, 'Non précisé') as order_type,
    total_cents,
    _ingested_at as ingested_at,
    _source_request_id as ingest_run_id
from source
