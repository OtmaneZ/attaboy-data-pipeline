-- Le rapport quotidien ne doit ni perdre ni inventer de ventes par rapport aux commandes.
with report as (
    select
        sum(net_sales) as net_sales,
        sum(orders) as orders
    from {{ ref('rpt_sales_daily') }}
),

facts as (
    select
        sum(net_sales) as net_sales,
        count(*) as orders
    from {{ ref('fct_orders') }}
)

select
    report.net_sales,
    facts.net_sales as expected_net_sales,
    report.orders,
    facts.orders as expected_orders
from report
cross join facts
where
    report.net_sales <> facts.net_sales
    or report.orders <> facts.orders
