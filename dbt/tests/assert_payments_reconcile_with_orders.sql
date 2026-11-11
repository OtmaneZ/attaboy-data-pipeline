-- Pour chaque commande, paiements − remboursements doit redonner le montant encaissé
-- de fct_orders (à 1 cent près) : la vue « caisse » et la vue « ventes » racontent la même histoire.
with paid as (
    select order_id, sum(total_paid) as total_paid
    from {{ ref('fct_payments') }}
    group by order_id
),

refunded as (
    select order_id, sum(total_refunded) as total_refunded
    from {{ ref('fct_refunds') }}
    group by order_id
)

select
    o.order_id,
    o.total_collected,
    coalesce(p.total_paid, 0) - coalesce(r.total_refunded, 0) as cash_net
from {{ ref('fct_orders') }} o
left join paid p
    on o.order_id = p.order_id
left join refunded r
    on o.order_id = r.order_id
where abs(o.total_collected - (coalesce(p.total_paid, 0) - coalesce(r.total_refunded, 0))) > 0.01
