-- Le total Clover d'une commande payée doit égaler : brut − rabais + taxes (à 1 cent près).
-- Une ligne retournée = une commande dont nos montants ne retombent pas sur ceux de la caisse.
select
    order_id,
    total_cents,
    gross_cents - discount_cents + tax_cents as recomputed_cents
from {{ ref('int_orders__amounts') }}
where payment_count is not null
    and abs(gross_cents - discount_cents + tax_cents - total_cents) > 1
