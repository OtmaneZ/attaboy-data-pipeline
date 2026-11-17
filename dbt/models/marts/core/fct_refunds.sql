-- Une ligne par remboursement, daté du moment où l'argent est ressorti
-- (et non de la commande d'origine, comme dans fct_orders).
with refunds as (
    select
        *,
        {{ local_ts('refunded_at_utc') }} as refunded_at_local
    from {{ ref('stg_clover__refunds') }}
),

payments as (
    select
        payment_id,
        tender_type
    from {{ ref('stg_clover__payments') }}
)

select
    r.refund_id,
    r.order_id,
    r.merchant_id,
    r.payment_id,
    r.refunded_at_local as refunded_at,
    {{ business_date('r.refunded_at_local') }} as refund_date,
    -- Un remboursement repart par le moyen de paiement d'origine.
    coalesce(p.tender_type, 'Inconnu') as tender_type,
    {{ cents_to_amount('r.amount_cents') }} as amount,
    {{ cents_to_amount('r.tax_cents') }} as tax_amount,
    {{ cents_to_amount('r.tip_cents') }} as tip_amount,
    {{ cents_to_amount('r.amount_cents + r.tip_cents') }} as total_refunded
from refunds r
left join payments p
    on r.payment_id = p.payment_id
