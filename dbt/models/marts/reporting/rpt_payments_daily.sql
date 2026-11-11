-- Caisse par jour et par moyen de paiement : ce qui est entré, ce qui est ressorti.
-- Chaque mouvement est compté le jour où il a eu lieu, comme sur le rapport de la caisse.
with movements as (
    select
        payment_date as movement_date,
        tender_type,
        1 as payments,
        total_paid as amount_paid,
        tip_amount,
        0 as refunds,
        cast(0 as decimal(18, 2)) as amount_refunded
    from {{ ref('fct_payments') }}

    union all

    select
        refund_date as movement_date,
        tender_type,
        0 as payments,
        cast(0 as decimal(18, 2)) as amount_paid,
        cast(0 as decimal(18, 2)) as tip_amount,
        1 as refunds,
        total_refunded as amount_refunded
    from {{ ref('fct_refunds') }}
)

select
    movement_date as payment_date,
    tender_type,
    sum(payments) as payments,
    sum(amount_paid) as amount_paid,
    sum(tip_amount) as tip_amount,
    sum(refunds) as refunds,
    sum(amount_refunded) as amount_refunded,
    sum(amount_paid) - sum(amount_refunded) as net_collected
from movements
group by movement_date, tender_type
