with src as (
    select * from {{ source('raw', 'raw_clover_payments') }}
)

select
    clover_payment_id,
    clover_order_id,
    merchant_id,
    amount_cents,
    (amount_cents / 100)::number(38, 2) as amount,
    tip_amount_cents,
    (tip_amount_cents / 100)::number(38, 2) as tip_amount,
    tax_amount_cents,
    (tax_amount_cents / 100)::number(38, 2) as tax_amount,
    result as payment_result,
    tender_type,
    created_time,
    modified_time,
    _ingested_at,
    _source_request_id
from src
