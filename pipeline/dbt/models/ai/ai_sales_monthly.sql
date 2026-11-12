-- Approved for the AI assistant: monthly sales by customer group, region, product group. Demo data only.
{{ config(alias='sales_monthly') }}
select invoice_month, customer_group, territory as region, item_group as product_group,
    invoices, units, revenue, cost, gross_margin, gross_margin_pct
from {{ ref('sales_monthly') }}
