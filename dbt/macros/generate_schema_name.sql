{% macro generate_schema_name(custom_schema_name, node) -%}
    {#- Toujours le schéma custom (analytics), jamais <target>_<custom>. -#}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
