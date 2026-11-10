{#- Clover stocke tous les montants en cents (entiers). Les marts exposent des dollars. -#}
{% macro cents_to_amount(column) -%}
    cast(({{ column }}) / 100.0 as decimal(18, 2))
{%- endmacro %}
