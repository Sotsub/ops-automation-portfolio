select
    name as supplier_id,
    data->>'supplier_name' as supplier_name,
    data->>'supplier_group' as supplier_group,
    data->>'country' as country
from {{ source('erpnext', 'erpnext_supplier') }}
