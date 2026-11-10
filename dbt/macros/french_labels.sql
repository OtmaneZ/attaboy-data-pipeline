{#- Libellés français indépendants du moteur et de la langue de la session. -#}
{% macro french_month_name(month_number) -%}
    case {{ month_number }}
        when 1 then 'janvier' when 2 then 'février' when 3 then 'mars'
        when 4 then 'avril' when 5 then 'mai' when 6 then 'juin'
        when 7 then 'juillet' when 8 then 'août' when 9 then 'septembre'
        when 10 then 'octobre' when 11 then 'novembre' when 12 then 'décembre'
    end
{%- endmacro %}

{% macro french_weekday_name(iso_weekday) -%}
    case {{ iso_weekday }}
        when 1 then 'lundi' when 2 then 'mardi' when 3 then 'mercredi'
        when 4 then 'jeudi' when 5 then 'vendredi' when 6 then 'samedi'
        when 7 then 'dimanche'
    end
{%- endmacro %}
