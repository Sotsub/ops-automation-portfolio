-- Approved for the AI assistant: receivables per aging bucket. Demo data only.
{{ config(alias='ar_aging') }}
select aging_bucket, bucket_order, invoices, outstanding_amount, as_of_date
from {{ ref('ar_aging') }}
