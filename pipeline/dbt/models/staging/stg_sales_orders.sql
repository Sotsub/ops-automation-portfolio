-- Submitted sales orders only (drafts and cancelled orders are not business facts yet).
select
    name as sales_order_id,
    data->>'customer' as customer_id,
    (data->>'transaction_date')::date as order_date,
    (data->>'delivery_date')::date as delivery_date,
    data->>'status' as status,
    (data->>'grand_total')::numeric as order_total,
    (data->>'per_billed')::numeric as percent_billed,
    data->>'po_no' as customer_po
from {{ source('erpnext', 'erpnext_sales_order') }}
where docstatus = 1
