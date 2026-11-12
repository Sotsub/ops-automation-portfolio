select
    name as bin_id,
    data->>'item_code' as item_code,
    data->>'warehouse' as warehouse,
    (data->>'actual_qty')::numeric as on_hand_qty,
    (data->>'ordered_qty')::numeric as on_order_qty,
    (data->>'reserved_qty')::numeric as reserved_qty,
    (data->>'projected_qty')::numeric as projected_qty,
    (data->>'valuation_rate')::numeric as valuation_rate,
    (data->>'stock_value')::numeric as stock_value
from {{ source('erpnext', 'erpnext_bin') }}
