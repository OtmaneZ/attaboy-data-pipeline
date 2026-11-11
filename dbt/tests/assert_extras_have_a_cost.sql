-- Un extra vendu sans coût dans seeds/extras_catalog.csv est compté à coût nul :
-- la marge du produit qui le porte est alors surévaluée. Avertissement, pas blocage.
{{ config(severity='warn') }}

select
    m.modifier_id,
    max(m.modifier_name) as modifier_name,
    count(*) as times_sold
from {{ ref('stg_clover__modifications') }} m
left join {{ ref('extras_catalog') }} c
    on m.modifier_id = c.modifier_id
where c.modifier_id is null
group by m.modifier_id
