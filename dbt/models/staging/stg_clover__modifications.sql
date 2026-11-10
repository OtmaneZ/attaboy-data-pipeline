-- Une ligne par extra ajouté à un article (extra fromage, pâte sans gluten…).
-- Les extras vivent dans le JSON de la ligne : on déplie le tableau.
with line_items as (
    select * from {{ source('clover', 'raw_clover_line_items') }}
)

select
    {{ json_text('m.value', 'id') }} as modification_id,
    li.clover_line_item_id as line_item_id,
    li.clover_order_id as order_id,
    li.merchant_id,
    {{ json_text('m.value', 'modifier.id') }} as modifier_id,
    {{ json_text('m.value', 'name') }} as modifier_name,
    coalesce({{ json_int('m.value', 'amount') }}, 0) as amount_cents
from line_items li,
    {{ json_flatten('li.payload', 'modifications.elements', 'm') }}
