-- Approved for the AI assistant: headline figures. Demo data only.
{{ config(alias='kpi_summary') }}
select * from {{ ref('kpi_summary') }}
