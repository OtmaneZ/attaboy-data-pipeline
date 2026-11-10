-- Tous les montants d'une commande, en cents, avant toute règle de présentation.
-- C'est ici que se décide ce qu'est une « vente nette » :
--   vente brute  = articles + extras (hors taxes)
--   vente nette  = vente brute − rabais − remboursements (hors taxes)
with orders as (
    select * from {{ ref('stg_clover__orders') }}
),

lines as (
    select
        order_id,
        count(*) as item_count,
        sum(gross_cents) as gross_cents
    from {{ ref('int_order_lines__priced') }}
    group by order_id
),

discounts as (
    select
        d.order_id,
        count(*) as discount_count,
        max(d.discount_name) as discount_name,
        -- Clover ne donne parfois que le pourcentage : on recalcule alors le montant.
        sum(coalesce(d.amount_cents, round(l.gross_cents * d.discount_percentage / 100.0))) as discount_cents
    from {{ ref('stg_clover__discounts') }} d
    inner join lines l
        on d.order_id = l.order_id
    group by d.order_id
),

payments as (
    select
        order_id,
        count(*) as payment_count,
        sum(amount_cents) as paid_cents,
        sum(tip_cents) as tip_cents,
        sum(tax_cents) as tax_cents,
        case when count(distinct tender_type) = 1 then max(tender_type) else 'Mixte' end as tender_type,
        max(paid_at_local) as paid_at_local
    from {{ ref('stg_clover__payments') }}
    where payment_result = 'SUCCESS'
    group by order_id
),

refunds as (
    select
        order_id,
        count(*) as refund_count,
        sum(amount_cents) as refund_cents,
        sum(tax_cents) as refund_tax_cents,
        sum(tip_cents) as refund_tip_cents
    from {{ ref('stg_clover__refunds') }}
    group by order_id
)

select
    o.order_id,
    o.merchant_id,
    o.created_at_local,
    o.order_type,
    o.order_state,
    o.payment_state,
    o.currency,
    o.total_cents,
    coalesce(l.item_count, 0) as item_count,
    coalesce(l.gross_cents, 0) as gross_cents,
    coalesce(d.discount_cents, 0) as discount_cents,
    d.discount_name,
    p.payment_count,
    p.paid_cents,
    p.tender_type,
    p.paid_at_local,
    coalesce(p.tax_cents, 0) as tax_cents,
    coalesce(p.tip_cents, 0) as tip_cents,
    coalesce(r.refund_count, 0) as refund_count,
    -- Part hors taxes du remboursement : c'est elle qui réduit la vente nette.
    coalesce(r.refund_cents, 0) - coalesce(r.refund_tax_cents, 0) as refund_net_cents,
    coalesce(r.refund_tax_cents, 0) as refund_tax_cents,
    coalesce(r.refund_tip_cents, 0) as refund_tip_cents
from orders o
left join lines l
    on o.order_id = l.order_id
left join discounts d
    on o.order_id = d.order_id
left join payments p
    on o.order_id = p.order_id
left join refunds r
    on o.order_id = r.order_id
