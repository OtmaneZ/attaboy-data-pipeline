{#-
    Jour de vente d'un horodatage local. Par défaut le jour civil. Pour un établissement
    ouvert après minuit, la var business_day_start_hour (ex. 4) rattache les ventes
    de 0 h à 3 h 59 à la veille : la soirée reste entière dans les rapports.
-#}
{% macro business_date(local_timestamp) -%}
    cast({{ dbt.dateadd('hour', -1 * (var('business_day_start_hour') | int), local_timestamp) }} as date)
{%- endmacro %}
