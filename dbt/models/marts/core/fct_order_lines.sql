-- Une ligne par article vendu, avec sa part de la vente nette de la commande.
-- Rabais et remboursements portent sur la commande entière : ils sont répartis
-- sur les articles au prorata de leur prix.
with lines as (
    select * from {{ ref('int_order_lines__priced') }}
),

orders as (
    select * from {{ ref('fct_orders') }}
),

products as (
    select * from {{ ref('dim_product') }}
)

select
    l.line_item_id,
    l.order_id,
    l.merchant_id,
    o.order_date,
    o.order_hour,
    o.order_type,
    l.product_id,
    p.product_name,
    p.category,
    {{ cents_to_amount('l.price_cents') }} as unit_price,
    l.extras_count,
    {{ cents_to_amount('l.extras_cents') }} as extras_amount,
    {{ cents_to_amount('l.gross_cents') }} as gross_sales,
    cast(
        case
            when o.gross_sales = 0 then 0
            else l.gross_cents / 100.0 * o.net_sales / o.gross_sales
        end as decimal(18, 4)
    ) as net_sales,
    -- Coût matière estimé de l'article (les extras ne sont pas chiffrés).
    p.estimated_unit_cost as estimated_cost
from lines l
inner join orders o
    on l.order_id = o.order_id
inner join products p
    on l.product_id = p.product_id
