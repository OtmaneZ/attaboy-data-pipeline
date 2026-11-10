-- La somme des ventes nettes des articles doit redonner la vente nette de la commande
-- (répartition des rabais et remboursements au prorata, tolérance de 2 cents).
with lines as (
    select
        order_id,
        sum(net_sales) as lines_net_sales
    from {{ ref('fct_order_lines') }}
    group by order_id
)

select
    o.order_id,
    o.net_sales,
    l.lines_net_sales
from {{ ref('fct_orders') }} o
inner join lines l
    on o.order_id = l.order_id
where abs(o.net_sales - l.lines_net_sales) > 0.02
