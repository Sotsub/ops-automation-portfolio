with defaults as (
    select parent as item_code, data->>'default_supplier' as default_supplier
    from {{ source('erpnext', 'erpnext_item_default') }}
),
reorder as (
    select
        parent as item_code,
        data->>'warehouse' as warehouse,
        (data->>'warehouse_reorder_level')::numeric as reorder_level,
        (data->>'warehouse_reorder_qty')::numeric as reorder_qty
    from {{ source('erpnext', 'erpnext_item_reorder') }}
)
select
    i.name as item_code,
    i.data->>'item_name' as item_name,
    i.data->>'item_group' as item_group,
    i.data->>'stock_uom' as uom,
    coalesce((i.data->>'is_stock_item')::int, 0) = 1 as is_stock_item,
    (i.data->>'standard_rate')::numeric as list_price,
    (i.data->>'valuation_rate')::numeric as standard_cost,
    d.default_supplier,
    r.warehouse as reorder_warehouse,
    r.reorder_level,
    r.reorder_qty
from {{ source('erpnext', 'erpnext_item') }} as i
left join defaults as d on d.item_code = i.name
left join reorder as r on r.item_code = i.name
