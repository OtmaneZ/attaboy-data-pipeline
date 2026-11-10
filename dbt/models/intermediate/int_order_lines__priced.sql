-- Chaque article avec ses extras : prix de l'article + suppléments = vente brute de la ligne.
with line_items as (
    select * from {{ ref('stg_clover__line_items') }}
),

extras as (
    select
        line_item_id,
        count(*) as extras_count,
        sum(amount_cents) as extras_cents
    from {{ ref('stg_clover__modifications') }}
    group by line_item_id
)

select
    li.line_item_id,
    li.order_id,
    li.merchant_id,
    li.product_id,
    li.product_name,
    li.price_cents,
    coalesce(e.extras_count, 0) as extras_count,
    coalesce(e.extras_cents, 0) as extras_cents,
    li.price_cents + coalesce(e.extras_cents, 0) as gross_cents
from line_items li
left join extras e
    on li.line_item_id = e.line_item_id
