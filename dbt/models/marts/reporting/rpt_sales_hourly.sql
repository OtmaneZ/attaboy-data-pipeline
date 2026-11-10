-- Affluence : commandes et ventes par jour et par heure (pour planifier les quarts).
select
    order_date,
    order_hour,
    count(*) as orders,
    sum(item_count) as items,
    sum(net_sales) as net_sales
from {{ ref('fct_orders') }}
group by order_date, order_hour
