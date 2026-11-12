-- Approved for the AI assistant: stock against reorder level. Demo data only.
{{ config(alias='inventory_status') }}
select item_code, item_name, item_group as product_group, uom, default_supplier, on_hand_qty,
    on_order_qty, reorder_level, reorder_qty, stock_value, units_sold_90d, days_of_cover,
    below_reorder_level, stock_status, as_of_date
from {{ ref('inventory_status') }}
