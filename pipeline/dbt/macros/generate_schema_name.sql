{#
  Use each model's schema name as written (staging, marts) instead of dbt's default
  "<target schema>_<custom schema>". This demo has one database and one environment, and the
  schemas are created by infra/postgres/init/10-bluefield.sh with these exact names.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
