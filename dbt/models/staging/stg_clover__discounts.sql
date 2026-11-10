-- Une ligne par rabais appliqué à une commande (promo midi, rabais employé…).
-- Clover donne soit un montant (négatif, en cents), soit seulement un pourcentage.
with orders as (
    select * from {{ source('clover', 'raw_clover_orders') }}
)

select
    {{ json_text('d.value', 'id') }} as discount_id,
    o.clover_order_id as order_id,
    o.merchant_id,
    {{ json_text('d.value', 'name') }} as discount_name,
    {{ json_int('d.value', 'percentage') }} as discount_percentage,
    abs({{ json_int('d.value', 'amount') }}) as amount_cents
from orders o,
    {{ json_flatten('o.payload', 'discounts.elements', 'd') }}
