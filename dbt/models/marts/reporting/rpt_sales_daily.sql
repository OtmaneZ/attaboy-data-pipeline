-- Une ligne par jour du calendrier, entre la première et la dernière vente.
-- Les jours de fermeture apparaissent avec des zéros : une courbe sans trou.
with calendar as (
    select * from {{ ref('dim_date') }}
),

orders as (
    select * from {{ ref('fct_orders') }}
),

bounds as (
    select
        min(order_date) as first_day,
        max(order_date) as last_day
    from orders
),

daily as (
    select
        order_date,
        count(*) as orders,
        sum(item_count) as items,
        sum(gross_sales) as gross_sales,
        sum(discount_amount) as discount_amount,
        sum(refund_amount) as refund_amount,
        sum(net_sales) as net_sales,
        sum(tax_amount) as tax_amount,
        sum(tip_amount) as tip_amount,
        sum(total_collected) as total_collected,
        sum(case when is_discounted then 1 else 0 end) as discounted_orders,
        sum(case when is_refunded then 1 else 0 end) as refunded_orders
    from orders
    group by order_date
),

joined as (
    select
        c.date_day,
        c.iso_weekday,
        c.weekday_name,
        c.week_start,
        c.month_start,
        c.is_weekend,
        coalesce(d.orders, 0) as orders,
        coalesce(d.items, 0) as items,
        coalesce(d.gross_sales, 0) as gross_sales,
        coalesce(d.discount_amount, 0) as discount_amount,
        coalesce(d.refund_amount, 0) as refund_amount,
        coalesce(d.net_sales, 0) as net_sales,
        coalesce(d.tax_amount, 0) as tax_amount,
        coalesce(d.tip_amount, 0) as tip_amount,
        coalesce(d.total_collected, 0) as total_collected,
        coalesce(d.discounted_orders, 0) as discounted_orders,
        coalesce(d.refunded_orders, 0) as refunded_orders
    from calendar c
    cross join bounds b
    left join daily d
        on c.date_day = d.order_date
    where c.date_day between b.first_day and b.last_day
)

select
    *,
    orders > 0 as is_open,
    cast(case when orders > 0 then net_sales / orders end as decimal(18, 2)) as average_ticket,
    -- Moyenne mobile seulement quand les 7 jours existent : pas de faux départ en début d'historique.
    case
        when count(*) over (order by date_day rows between 6 preceding and current row) = 7
            then cast(
                avg(net_sales) over (order by date_day rows between 6 preceding and current row)
                as decimal(18, 2)
            )
    end as net_sales_7d_avg,
    lag(net_sales, 7) over (order by date_day) as net_sales_same_weekday_last_week
from joined
