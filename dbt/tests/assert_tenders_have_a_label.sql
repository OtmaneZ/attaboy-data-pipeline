-- Un moyen de paiement absent de seeds/tender_labels.csv s'affiche avec le libellé brut
-- de la caisse (souvent en anglais). Avertissement, pas blocage.
{{ config(severity='warn') }}

select
    p.tender_label_key,
    max(p.tender_type) as shown_as,
    count(*) as payments
from {{ ref('stg_clover__payments') }} p
left join {{ ref('tender_labels') }} l
    on p.tender_label_key = l.label_key
where l.label_key is null
group by p.tender_label_key
