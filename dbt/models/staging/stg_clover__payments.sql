-- Une ligne par paiement. Montants en cents, pourboire et taxes séparés.
with source as (
    select * from {{ source('clover', 'raw_clover_payments') }}
)

select
    clover_payment_id as payment_id,
    clover_order_id as order_id,
    merchant_id,
    amount_cents,
    coalesce(tip_amount_cents, 0) as tip_cents,
    coalesce(tax_amount_cents, 0) as tax_cents,
    upper(result) as payment_result,
    coalesce(tender_type, 'Inconnu') as tender_type,
    created_time as paid_at_utc,
    {{ local_ts('created_time') }} as paid_at_local
from source
