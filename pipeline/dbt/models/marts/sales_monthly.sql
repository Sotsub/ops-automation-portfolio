-- Monthly sales by customer group, region and product group. Demo data only.
select
    invoice_month,
    customer_group,
    territory,
    item_group,
    count(distinct invoice_id) as invoices,
    sum(qty) as units,
    sum(revenue) as revenue,
    sum(cost) as cost,
    sum(gross_margin) as gross_margin,
    round(100 * sum(gross_margin) / nullif(sum(revenue), 0), 1) as gross_margin_pct
from {{ ref('sales_lines') }}
group by invoice_month, customer_group, territory, item_group
