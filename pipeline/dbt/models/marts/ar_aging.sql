-- Accounts receivable aging: every bucket, even when empty. Demo data only.
with buckets (aging_bucket, bucket_order) as (
    values ('Current', 1), ('1-30 days', 2), ('31-60 days', 3), ('61-90 days', 4), ('Over 90 days', 5)
)
select
    b.aging_bucket,
    b.bucket_order,
    count(o.invoice_id) as invoices,
    coalesce(sum(o.outstanding_amount), 0) as outstanding_amount,
    {{ as_of_date() }} as as_of_date
from buckets as b
left join {{ ref('ar_open_invoices') }} as o on o.aging_bucket = b.aging_bucket
group by b.aging_bucket, b.bucket_order
