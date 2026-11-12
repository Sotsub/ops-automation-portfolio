-- One row of headline numbers for the dashboards, all calculated here in SQL. Demo data only.
select
    {{ as_of_date() }} as as_of_date,
    (select max(loaded_at) from {{ source('erpnext', 'erpnext_sales_invoice') }}) as data_loaded_at,
    now() as built_at,
    (select count(*) from {{ ref('stg_sales_invoices') }}) as invoices,
    (select sum(revenue) from {{ ref('sales_lines') }}) as revenue,
    (select sum(gross_margin) from {{ ref('sales_lines') }}) as gross_margin,
    (select round(100 * sum(gross_margin) / nullif(sum(revenue), 0), 1) from {{ ref('sales_lines') }})
        as gross_margin_pct,
    (select coalesce(sum(outstanding_amount), 0) from {{ ref('ar_open_invoices') }}) as open_receivables,
    (select coalesce(sum(outstanding_amount), 0) from {{ ref('ar_open_invoices') }} where days_overdue > 0)
        as overdue_receivables,
    (select count(*) from {{ ref('ar_open_invoices') }} where days_overdue > 0) as overdue_invoices,
    (select coalesce(sum(outstanding_amount), 0) from {{ ref('stg_purchase_invoices') }}) as open_payables,
    (select count(*) from {{ ref('inventory_status') }} where below_reorder_level) as items_below_reorder,
    (select count(*) from {{ ref('stg_sales_orders') }} where status like 'To %') as open_sales_orders,
    (select count(*) from {{ ref('stg_purchase_orders') }} where status like 'To %') as open_purchase_orders
