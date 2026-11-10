-- Une ligne par remboursement. Le montant inclut les taxes, pas le pourboire.
with orders as (
    select * from {{ source('clover', 'raw_clover_orders') }}
)

select
    {{ json_text('r.value', 'id') }} as refund_id,
    o.clover_order_id as order_id,
    o.merchant_id,
    {{ json_text('r.value', 'payment.id') }} as payment_id,
    coalesce({{ json_int('r.value', 'amount') }}, 0) as amount_cents,
    coalesce({{ json_int('r.value', 'taxAmount') }}, 0) as tax_cents,
    coalesce({{ json_int('r.value', 'tipAmount') }}, 0) as tip_cents,
    {{ epoch_ms_to_ts(json_int('r.value', 'createdTime')) }} as refunded_at_utc
from orders o,
    {{ json_flatten('o.payload', 'refunds.elements', 'r') }}
