-- Une ligne par paiement réussi, daté du moment où l'argent est entré.
-- C'est la table du rapprochement de caisse : fct_orders répond à « qu'ai-je vendu »,
-- fct_payments à « qu'ai-je encaissé, quand et par quel moyen ».
with payments as (
    select * from {{ ref('stg_clover__payments') }}
    where payment_result = 'SUCCESS'
)

select
    payment_id,
    order_id,
    merchant_id,
    paid_at_local as paid_at,
    {{ business_date('paid_at_local') }} as payment_date,
    tender_type,
    {{ cents_to_amount('amount_cents') }} as amount,
    {{ cents_to_amount('tax_cents') }} as tax_amount,
    {{ cents_to_amount('tip_cents') }} as tip_amount,
    {{ cents_to_amount('amount_cents + tip_cents') }} as total_paid
from payments
