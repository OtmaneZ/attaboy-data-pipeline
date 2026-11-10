{#-
    Les modèles tournent sur deux moteurs : Snowflake (le projet) et DuckDB
    (démo locale et CI, sans crédit). Les rares différences de syntaxe sont
    isolées ici. La version « default » est celle de Snowflake.
-#}

{#- Heure UTC → heure locale du restaurant (sans fuseau). -#}
{% macro local_ts(column) -%}
    {{ return(adapter.dispatch('local_ts')(column)) }}
{%- endmacro %}

{% macro default__local_ts(column) -%}
    convert_timezone('{{ var("local_timezone") }}', {{ column }})::timestamp_ntz
{%- endmacro %}

{% macro duckdb__local_ts(column) -%}
    timezone('{{ var("local_timezone") }}', {{ column }})
{%- endmacro %}


{#- Champ texte d'un JSON brut. Chemin avec des points : 'orderType.label'. -#}
{% macro json_text(column, path) -%}
    {{ return(adapter.dispatch('json_text')(column, path)) }}
{%- endmacro %}

{% macro default__json_text(column, path) -%}
    get_path({{ column }}, '{{ path }}')::varchar
{%- endmacro %}

{% macro duckdb__json_text(column, path) -%}
    json_extract_string({{ column }}, '$.{{ path }}')
{%- endmacro %}


{#- Champ entier d'un JSON brut (montants Clover en cents, horodatages en ms). -#}
{% macro json_int(column, path) -%}
    {{ return(adapter.dispatch('json_int')(column, path)) }}
{%- endmacro %}

{% macro default__json_int(column, path) -%}
    get_path({{ column }}, '{{ path }}')::number(38, 0)
{%- endmacro %}

{% macro duckdb__json_int(column, path) -%}
    cast(json_extract_string({{ column }}, '$.{{ path }}') as bigint)
{%- endmacro %}


{#-
    Déplie un tableau JSON : une ligne par élément, accessible via <alias>.value.
    S'utilise dans le FROM, après une virgule. Tableau absent = aucune ligne.
-#}
{% macro json_flatten(column, path, alias) -%}
    {{ return(adapter.dispatch('json_flatten')(column, path, alias)) }}
{%- endmacro %}

{% macro default__json_flatten(column, path, alias) -%}
    lateral flatten(input => get_path({{ column }}, '{{ path }}')) {{ alias }}
{%- endmacro %}

{% macro duckdb__json_flatten(column, path, alias) -%}
    json_each({{ column }}, '$.{{ path }}') {{ alias }}
{%- endmacro %}


{#- Horodatage Clover (millisecondes depuis 1970) → timestamp avec fuseau. -#}
{% macro epoch_ms_to_ts(expression) -%}
    {{ return(adapter.dispatch('epoch_ms_to_ts')(expression)) }}
{%- endmacro %}

{% macro default__epoch_ms_to_ts(expression) -%}
    to_timestamp_tz({{ expression }}, 3)
{%- endmacro %}

{% macro duckdb__epoch_ms_to_ts(expression) -%}
    to_timestamp({{ expression }} / 1000.0)
{%- endmacro %}


{#- Jour de la semaine ISO : 1 = lundi … 7 = dimanche. -#}
{% macro iso_weekday(date_column) -%}
    {{ return(adapter.dispatch('iso_weekday')(date_column)) }}
{%- endmacro %}

{% macro default__iso_weekday(date_column) -%}
    dayofweekiso({{ date_column }})
{%- endmacro %}

{% macro duckdb__iso_weekday(date_column) -%}
    isodow({{ date_column }})
{%- endmacro %}
