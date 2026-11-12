-- Stock position per product against its reorder level, with recent demand. Demo data only.
with sold_90d as (
    select l.item_code, sum(l.qty) as units
    from {{ ref('stg_sales_invoice_lines') }} as l
    join {{ ref('stg_sales_invoices') }} as i on i.invoice_id = l.invoice_id
    where i.invoice_date > {{ as_of_date() }} - 90 and i.invoice_date <= {{ as_of_date() }}
    group by l.item_code
)
select
    it.item_code,
    it.item_name,
    it.item_group,
    it.uom,
    it.default_supplier,
    coalesce(s.on_hand_qty, 0) as on_hand_qty,
    coalesce(s.on_order_qty, 0) as on_order_qty,
    it.reorder_level,
    it.reorder_qty,
    coalesce(s.stock_value, 0) as stock_value,
    coalesce(d.units, 0) as units_sold_90d,
    case when d.units > 0 then round(coalesce(s.on_hand_qty, 0) / (d.units / 90.0), 1) end as days_of_cover,
    coalesce(s.on_hand_qty, 0) <= it.reorder_level as below_reorder_level,
    case
        when coalesce(s.on_hand_qty, 0) = 0 then 'Out of stock'
        when coalesce(s.on_hand_qty, 0) <= it.reorder_level then 'Below reorder level'
        else 'OK'
    end as stock_status,
    {{ as_of_date() }} as as_of_date
from {{ ref('stg_items') }} as it
left join {{ ref('stg_stock_levels') }} as s
    on s.item_code = it.item_code and s.warehouse = it.reorder_warehouse
left join sold_90d as d on d.item_code = it.item_code
where it.is_stock_item
