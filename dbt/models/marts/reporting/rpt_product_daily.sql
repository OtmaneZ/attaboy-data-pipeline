-- Ventes par jour et par produit.
select
    order_date,
    product_id,
    max(product_name) as product_name,
    max(category) as category,
    count(*) as quantity,
    sum(gross_sales) as gross_sales,
    cast(sum(net_sales) as decimal(18, 2)) as net_sales,
    sum(estimated_cost) as estimated_cost,
    sum(case when extras_count > 0 then 1 else 0 end) as lines_with_extras,
    sum(extras_amount) as extras_amount
from {{ ref('fct_order_lines') }}
group by order_date, product_id
