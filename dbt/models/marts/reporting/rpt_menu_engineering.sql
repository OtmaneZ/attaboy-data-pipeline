-- Ingénierie de menu (méthode Kasavana-Smith), par catégorie, sur les jours de données (fenêtre : var menu_window_days).
--
--   popularité : part des ventes de la catégorie, comparée au seuil 70 % × (1 / nombre de produits)
--   rentabilité : marge unitaire, comparée à la marge unitaire moyenne de la catégorie
--
--              | marge forte   | marge faible
--   populaire  | Vedette       | Valeur sûre
--   peu vendu  | Énigme        | Poids mort
with lines as (
    select * from {{ ref('fct_order_lines') }}
    where estimated_cost is not null
),

bounds as (
    select max(order_date) as last_day from lines
),

recent as (
    select l.*
    from lines l
    cross join bounds b
    where l.order_date > b.last_day - {{ var('menu_window_days') }}
),

by_product as (
    select
        product_id,
        max(product_name) as product_name,
        max(category) as category,
        count(*) as quantity_sold,
        sum(net_sales) as net_sales,
        sum(estimated_cost) as estimated_cost,
        sum(net_sales) - sum(estimated_cost) as contribution_margin
    from recent
    group by product_id
),

scored as (
    select
        *,
        contribution_margin / quantity_sold as unit_margin,
        quantity_sold * 1.0 / sum(quantity_sold) over (partition by category) as mix_share,
        0.7 / count(*) over (partition by category) as popularity_threshold,
        sum(contribution_margin) over (partition by category)
            / sum(quantity_sold) over (partition by category) as category_unit_margin
    from by_product
),

classified as (
    select
        *,
        mix_share >= popularity_threshold as is_popular,
        unit_margin >= category_unit_margin as is_profitable
    from scored
)

select
    product_id,
    product_name,
    category,
    quantity_sold,
    cast(net_sales as decimal(18, 2)) as net_sales,
    cast(estimated_cost as decimal(18, 2)) as estimated_cost,
    cast(contribution_margin as decimal(18, 2)) as contribution_margin,
    cast(unit_margin as decimal(18, 2)) as unit_margin,
    cast(category_unit_margin as decimal(18, 2)) as category_unit_margin,
    cast(mix_share as decimal(9, 4)) as mix_share,
    cast(popularity_threshold as decimal(9, 4)) as popularity_threshold,
    case
        when is_popular and is_profitable then 'Vedette'
        when is_popular then 'Valeur sûre'
        when is_profitable then 'Énigme'
        else 'Poids mort'
    end as menu_class,
    case
        when is_popular and is_profitable then 'À mettre en avant, ne rien changer'
        when is_popular then 'Revoir le prix ou le coût de la recette'
        when is_profitable then 'À mieux faire connaître (carte, suggestion du personnel)'
        else 'À retravailler ou à retirer de la carte'
    end as recommended_action
from classified
