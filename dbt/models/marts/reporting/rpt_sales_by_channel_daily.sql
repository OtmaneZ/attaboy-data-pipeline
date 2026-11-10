-- Ventes par jour et par type de commande (sur place, à emporter, livraison).
select
    order_date,
    order_type,
    count(*) as orders,
    sum(net_sales) as net_sales,
    sum(tip_amount) as tip_amount
from {{ ref('fct_orders') }}
group by order_date, order_type
