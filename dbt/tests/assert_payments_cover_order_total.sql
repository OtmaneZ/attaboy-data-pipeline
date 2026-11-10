-- Les paiements réussis d'une commande payée doivent couvrir son total.
select
    order_id,
    total_cents,
    paid_cents
from {{ ref('int_orders__amounts') }}
where payment_count is not null
    and payment_state in ('PAID', 'REFUNDED')
    and paid_cents <> total_cents
