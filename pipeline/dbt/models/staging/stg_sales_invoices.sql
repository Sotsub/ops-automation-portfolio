-- Submitted sales invoices only.
select
    name as invoice_id,
    data->>'customer' as customer_id,
    (data->>'posting_date')::date as invoice_date,
    (data->>'due_date')::date as due_date,
    data->>'status' as status,
    coalesce((data->>'is_return')::int, 0) = 1 as is_return,
    (data->>'net_total')::numeric as net_total,
    (data->>'grand_total')::numeric as grand_total,
    coalesce((data->>'rounded_total')::numeric, 0) as rounded_total,
    (data->>'outstanding_amount')::numeric as outstanding_amount,
    data->>'currency' as currency,
    data->>'po_no' as customer_po
from {{ source('erpnext', 'erpnext_sales_invoice') }}
where docstatus = 1
