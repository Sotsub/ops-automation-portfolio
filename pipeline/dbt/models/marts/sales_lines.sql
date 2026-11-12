-- One row per invoiced product line, with customer and product attributes. Demo data only.
select
    l.line_id,
    l.invoice_id,
    i.invoice_date,
    date_trunc('month', i.invoice_date)::date as invoice_month,
    i.customer_id,
    c.customer_name,
    c.customer_group,
    c.territory,
    l.item_code,
    it.item_name,
    it.item_group,
    l.qty,
    l.net_amount as revenue,
    round(l.cost_amount, 2) as cost,
    round(l.net_amount - l.cost_amount, 2) as gross_margin
from {{ ref('stg_sales_invoice_lines') }} as l
join {{ ref('stg_sales_invoices') }} as i on i.invoice_id = l.invoice_id
left join {{ ref('stg_customers') }} as c on c.customer_id = i.customer_id
left join {{ ref('stg_items') }} as it on it.item_code = l.item_code
