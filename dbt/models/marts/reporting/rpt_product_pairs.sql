-- Produits souvent commandés ensemble, sur les derniers jours de données (fenêtre : var menu_window_days).
-- lift > 1 : la paire revient plus souvent que si les deux produits étaient choisis au hasard.
with lines as (
    select * from {{ ref('fct_order_lines') }}
),

bounds as (
    select max(order_date) as last_day from lines
),

order_products as (
    select distinct
        l.order_id,
        l.product_id,
        l.product_name,
        l.category
    from lines l
    cross join bounds b
    where l.order_date > b.last_day - {{ var('menu_window_days') }}
),

totals as (
    select count(distinct order_id) as total_orders from order_products
),

product_orders as (
    select
        product_id,
        max(product_name) as product_name,
        max(category) as category,
        count(*) as orders_with_product
    from order_products
    group by product_id
),

pairs as (
    select
        a.product_id as product_a_id,
        b.product_id as product_b_id,
        count(*) as orders_together
    from order_products a
    inner join order_products b
        on
            a.order_id = b.order_id
            and a.product_id < b.product_id
    group by a.product_id, b.product_id
)

select
    pairs.product_a_id,
    pa.product_name as product_a_name,
    pa.category as product_a_category,
    pairs.product_b_id,
    pb.product_name as product_b_name,
    pb.category as product_b_category,
    pairs.orders_together,
    cast(pairs.orders_together * 1.0 / totals.total_orders as decimal(9, 4)) as support,
    cast(pairs.orders_together * 1.0 / pa.orders_with_product as decimal(9, 4)) as confidence_a_to_b,
    cast(pairs.orders_together * 1.0 / pb.orders_with_product as decimal(9, 4)) as confidence_b_to_a,
    cast(
        pairs.orders_together * 1.0 * totals.total_orders
        / (pa.orders_with_product * pb.orders_with_product)
        as decimal(9, 3)
    ) as lift
from pairs
cross join totals
inner join product_orders pa
    on pairs.product_a_id = pa.product_id
inner join product_orders pb
    on pairs.product_b_id = pb.product_id
where pairs.orders_together >= {{ var('pairs_min_orders') }}
