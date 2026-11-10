with orders as (
    select * from {{ ref('stg_clover_orders') }}
),

lines as (
    select * from {{ ref('stg_clover_line_items') }}
)

select
    l.clover_line_item_id,
    l.clover_order_id,
    l.merchant_id,
    o.created_time as order_created_time,
    convert_timezone('America/Toronto', o.created_time)::date as order_date_toronto,
    o.state as order_state,
    o.payment_state,
    o.currency,
    o.total_amount as order_total_amount,
    l.item_name,
    l.clover_item_id,
    l.unit_qty,
    l.price_amount as line_price_amount,
    l.created_time as line_created_time,
    l._ingested_at as line_ingested_at
from lines l
inner join orders o
    on o.clover_order_id = l.clover_order_id
