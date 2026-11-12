-- Lines of submitted sales invoices. cost_amount uses ERPNext's own valuation at the time of sale
-- (incoming_rate), so margins match ERPNext's cost of goods sold.
select
    l.name as line_id,
    l.parent as invoice_id,
    l.data->>'item_code' as item_code,
    l.data->>'sales_order' as sales_order_id,
    (l.data->>'qty')::numeric as qty,
    (l.data->>'rate')::numeric as rate,
    (l.data->>'net_amount')::numeric as net_amount,
    (l.data->>'qty')::numeric * coalesce((l.data->>'incoming_rate')::numeric, 0) as cost_amount
from {{ source('erpnext', 'erpnext_sales_invoice_item') }} as l
join {{ source('erpnext', 'erpnext_sales_invoice') }} as h on h.name = l.parent
where h.docstatus = 1
