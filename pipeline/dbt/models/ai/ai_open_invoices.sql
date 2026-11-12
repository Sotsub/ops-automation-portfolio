-- Approved for the AI assistant: unpaid sales invoices and how overdue they are. Demo data only.
{{ config(alias='open_invoices') }}
select invoice_id, customer_name, customer_group, territory as region, invoice_date, due_date,
    invoice_amount, outstanding_amount, days_overdue, aging_bucket, as_of_date
from {{ ref('ar_open_invoices') }}
