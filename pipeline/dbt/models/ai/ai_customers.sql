-- Approved for the AI assistant: customer revenue and payment habits. No contact details. Demo data only.
{{ config(alias='customers') }}
select customer_name, customer_group, territory as region, first_invoice_date, last_invoice_date,
    invoices, lifetime_revenue, invoices_paid, avg_days_to_pay, pct_paid_late, open_balance,
    overdue_balance
from {{ ref('customers') }}
