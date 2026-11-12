select item_code, on_hand_qty from {{ ref('inventory_status') }} where on_hand_qty < 0
