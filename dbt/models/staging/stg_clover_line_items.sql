with src as (
    select * from {{ source('raw', 'raw_clover_line_items') }}
)

select
    clover_line_item_id,
    clover_order_id,
    merchant_id,
    name as item_name,
    price_cents,
    (price_cents / 100)::number(38, 2) as price_amount,
    unit_qty,
    item_id as clover_item_id,
    created_time,
    modified_time,
    _ingested_at,
    _source_request_id
from src
