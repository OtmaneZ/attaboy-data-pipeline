-- Une ligne par produit vendu au moins une fois. La catégorie et le coût estimé
-- viennent du fichier seeds/menu_catalog.csv, tenu à la main avec le propriétaire.
with lines as (
    select
        l.product_id,
        l.product_name,
        l.price_cents,
        o.created_at_local
    from {{ ref('int_order_lines__priced') }} l
    inner join {{ ref('stg_clover__orders') }} o
        on l.order_id = o.order_id
),

latest as (
    -- Nom et prix les plus récents : un produit peut être renommé ou changer de prix.
    select product_id, product_name, price_cents
    from lines
    qualify row_number() over (partition by product_id order by created_at_local desc, product_name) = 1
),

history as (
    select
        product_id,
        cast(min(created_at_local) as date) as first_sold_date,
        cast(max(created_at_local) as date) as last_sold_date
    from lines
    group by product_id
),

catalog as (
    select * from {{ ref('menu_catalog') }}
)

select
    latest.product_id,
    latest.product_name,
    coalesce(catalog.category, 'Non classé') as category,
    {{ cents_to_amount('latest.price_cents') }} as list_price,
    catalog.estimated_unit_cost,
    catalog.product_id is not null as is_in_catalog,
    history.first_sold_date,
    history.last_sold_date
from latest
inner join history
    on latest.product_id = history.product_id
left join catalog
    on latest.product_id = catalog.product_id
