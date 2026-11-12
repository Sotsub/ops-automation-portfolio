-- Submitted purchase orders only.
select
    name as purchase_order_id,
    data->>'supplier' as supplier_id,
    (data->>'transaction_date')::date as order_date,
    (data->>'schedule_date')::date as expected_date,
    data->>'status' as status,
    (data->>'grand_total')::numeric as order_total,
    (data->>'per_received')::numeric as percent_received
from {{ source('erpnext', 'erpnext_purchase_order') }}
where docstatus = 1
