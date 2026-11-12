select
    name as customer_id,
    data->>'customer_name' as customer_name,
    data->>'customer_group' as customer_group,
    data->>'territory' as territory,
    data->>'email_id' as email,
    coalesce((data->>'disabled')::int, 0) = 1 as is_disabled
from {{ source('erpnext', 'erpnext_customer') }}
