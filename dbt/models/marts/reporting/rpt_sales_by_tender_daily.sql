-- Encaissements par jour et par moyen de paiement.
select
    order_date,
    tender_type,
    count(*) as orders,
    sum(total_collected) as total_collected
from {{ ref('fct_orders') }}
group by order_date, tender_type
