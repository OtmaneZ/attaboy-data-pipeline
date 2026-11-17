-- Une ligne par commande payée. Montants en dollars, hors taxes sauf mention contraire.
-- Les commandes jamais payées (panier abandonné, erreur de saisie) ne sont pas des ventes.
with amounts as (
    select * from {{ ref('int_orders__amounts') }}
    where payment_count is not null
),

computed as (
    select
        *,
        gross_cents - discount_cents - refund_net_cents as net_cents,
        tax_cents - refund_tax_cents as net_tax_cents,
        tip_cents - refund_tip_cents as net_tip_cents
    from amounts
)

select
    order_id,
    merchant_id,
    created_at_local as ordered_at,
    {{ business_date('created_at_local') }} as order_date,
    cast(extract(hour from created_at_local) as integer) as order_hour,
    order_type,
    tender_type,
    payment_state,
    currency,
    item_count,
    {{ cents_to_amount('gross_cents') }} as gross_sales,
    {{ cents_to_amount('discount_cents') }} as discount_amount,
    discount_name,
    {{ cents_to_amount('refund_net_cents') }} as refund_amount,
    {{ cents_to_amount('net_cents') }} as net_sales,
    {{ cents_to_amount('net_tax_cents') }} as tax_amount,
    {{ cents_to_amount('net_tip_cents') }} as tip_amount,
    {{ cents_to_amount('net_cents + net_tax_cents + net_tip_cents') }} as total_collected,
    discount_cents > 0 as is_discounted,
    refund_count > 0 as is_refunded,
    -- Ligne longue une fois la macro développée par l'adaptateur, pas dans le source.
    {{ dbt.datediff('created_at_local', 'paid_at_local', 'minute') }} as minutes_to_payment -- noqa: LT05
from computed
