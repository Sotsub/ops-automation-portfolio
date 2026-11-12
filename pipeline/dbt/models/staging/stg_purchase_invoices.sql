-- Submitted supplier bills only.
select
    name as purchase_invoice_id,
    data->>'supplier' as supplier_id,
    (data->>'posting_date')::date as bill_date,
    (data->>'due_date')::date as due_date,
    data->>'status' as status,
    (data->>'grand_total')::numeric as grand_total,
    (data->>'outstanding_amount')::numeric as outstanding_amount,
    data->>'bill_no' as supplier_bill_no
from {{ source('erpnext', 'erpnext_purchase_invoice') }}
where docstatus = 1
