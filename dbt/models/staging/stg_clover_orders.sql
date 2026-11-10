with src as (
    select * from {{ source('raw', 'raw_clover_orders') }}
)

select
    clover_order_id,
    merchant_id,
    created_time,
    modified_time,
    client_created_time,
    state,
    currency,
    total_cents,
    (total_cents / 100)::number(38, 2) as total_amount,
    payment_state,
    title,
    note,
    _ingested_at,
    _source_request_id
from src
