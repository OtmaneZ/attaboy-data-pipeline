-- Une ligne par paiement. Montants en cents, pourboire et taxes séparés.
-- La caisse nomme ses moyens de paiement en anglais (« Credit Card ») mais fournit une clé stable :
-- seeds/tender_labels.csv donne le libellé affiché. Clé inconnue = libellé de la caisse, tel quel.
with source as (
    select
        *,
        {{ json_text('payload', 'tender.labelKey') }} as tender_label_key
    from {{ source('clover', 'raw_clover_payments') }}
),

labels as (
    select * from {{ ref('tender_labels') }}
)

select
    s.clover_payment_id as payment_id,
    s.clover_order_id as order_id,
    s.merchant_id,
    s.amount_cents,
    coalesce(s.tip_amount_cents, 0) as tip_cents,
    coalesce(s.tax_amount_cents, 0) as tax_cents,
    upper(s.result) as payment_result,
    s.tender_label_key,
    coalesce(l.tender_label, s.tender_type, 'Inconnu') as tender_type,
    s.created_time as paid_at_utc,
    {{ local_ts('s.created_time') }} as paid_at_local
from source s
left join labels l
    on s.tender_label_key = l.label_key
