with order_lines as (
    select * from {{ ref('fct_order_lines') }}
),

payments as (
    select * from {{ ref('stg_clover_payments') }}
),

orders_daily as (
    select
        merchant_id,
        order_date_toronto as sales_date,
        count(distinct clover_order_id) as order_count,
        count(*) as line_count,
        sum(line_price_amount) as gross_line_amount
    from order_lines
    where order_date_toronto is not null
    group by 1, 2
),

payments_daily as (
    select
        merchant_id,
        convert_timezone('America/Toronto', created_time)::date as sales_date,
        count(*) as payment_count,
        sum(amount) as payment_amount,
        sum(coalesce(tip_amount, 0)) as tip_amount,
        sum(coalesce(tax_amount, 0)) as tax_amount
    from payments
    where created_time is not null
    group by 1, 2
)

select
    coalesce(o.merchant_id, p.merchant_id) as merchant_id,
    coalesce(o.sales_date, p.sales_date) as sales_date,
    coalesce(o.merchant_id, p.merchant_id)
        || '|'
        || to_char(coalesce(o.sales_date, p.sales_date), 'YYYY-MM-DD') as sales_day_sk,
    coalesce(o.order_count, 0) as order_count,
    coalesce(o.line_count, 0) as line_count,
    o.gross_line_amount,
    coalesce(p.payment_count, 0) as payment_count,
    p.payment_amount,
    p.tip_amount,
    p.tax_amount
from orders_daily o
full outer join payments_daily p
    on o.merchant_id = p.merchant_id
    and o.sales_date = p.sales_date
