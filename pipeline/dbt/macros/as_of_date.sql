{# The date reports are measured from: the as_of_date var if set, otherwise today. #}
{% macro as_of_date() -%}
    {%- if var('as_of_date', '') -%}
        date '{{ var("as_of_date") }}'
    {%- else -%}
        current_date
    {%- endif -%}
{%- endmacro %}
