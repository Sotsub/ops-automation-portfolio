-- Supplier bills per month. Demo data only.
select
    date_trunc('month', b.bill_date)::date as bill_month,
    b.supplier_id,
    s.supplier_group,
    count(*) as bills,
    sum(b.grand_total) as billed_amount,
    sum(b.outstanding_amount) as outstanding_amount
from {{ ref('stg_purchase_invoices') }} as b
left join {{ ref('stg_suppliers') }} as s on s.supplier_id = b.supplier_id
group by date_trunc('month', b.bill_date)::date, b.supplier_id, s.supplier_group
