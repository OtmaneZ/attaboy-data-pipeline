-- Chaque article avec ses extras : prix de l'article + suppléments = vente brute de la ligne.
-- Le coût matière des extras vient de seeds/extras_catalog.csv : un extra payant a aussi un coût.
with line_items as (
    select * from {{ ref('stg_clover__line_items') }}
),

extras as (
    select
        m.line_item_id,
        count(*) as extras_count,
        sum(m.amount_cents) as extras_cents,
        sum(coalesce(c.estimated_unit_cost, 0)) as extras_estimated_cost,
        sum(case when c.modifier_id is null then 1 else 0 end) as extras_without_cost
    from {{ ref('stg_clover__modifications') }} m
    left join {{ ref('extras_catalog') }} c
        on m.modifier_id = c.modifier_id
    group by m.line_item_id
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
    li.price_cents + coalesce(e.extras_cents, 0) as gross_cents,
    cast(coalesce(e.extras_estimated_cost, 0) as decimal(18, 2)) as extras_estimated_cost,
    coalesce(e.extras_without_cost, 0) as extras_without_cost
from line_items li
left join extras e
    on li.line_item_id = e.line_item_id
