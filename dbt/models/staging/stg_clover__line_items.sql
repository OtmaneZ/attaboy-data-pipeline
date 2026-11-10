-- Une ligne par article vendu. Clover crée une ligne par unité : quantité = 1.
with source as (
    select * from {{ source('clover', 'raw_clover_line_items') }}
)

select
    clover_line_item_id as line_item_id,
    clover_order_id as order_id,
    merchant_id,
    -- Un article saisi à la main n'a pas de fiche produit dans Clover.
    coalesce(item_id, 'hors-carte:' || name) as product_id,
    name as product_name,
    price_cents,
    created_time as created_at_utc
from source
