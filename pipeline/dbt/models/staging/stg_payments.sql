-- Submitted payments, one row per invoice each payment settles.
select
    r.name as payment_reference_id,
    p.name as payment_id,
    p.data->>'payment_type' as payment_type,
    p.data->>'party_type' as party_type,
    p.data->>'party' as party_id,
    (p.data->>'posting_date')::date as payment_date,
    p.data->>'mode_of_payment' as mode_of_payment,
    r.data->>'reference_doctype' as reference_doctype,
    r.data->>'reference_name' as reference_id,
    (r.data->>'allocated_amount')::numeric as allocated_amount
from {{ source('erpnext', 'erpnext_payment_entry_reference') }} as r
join {{ source('erpnext', 'erpnext_payment_entry') }} as p on p.name = r.parent
where p.docstatus = 1
