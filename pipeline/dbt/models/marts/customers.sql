-- One row per customer: who they are, what they buy, and how they pay. Demo data only.
with paid_dates as (
    select reference_id as invoice_id, max(payment_date) as paid_date
    from {{ ref('stg_payments') }}
    where reference_doctype = 'Sales Invoice'
    group by reference_id
),
invoices as (
    select i.*, p.paid_date, i.outstanding_amount = 0 as is_paid
    from {{ ref('stg_sales_invoices') }} as i
    left join paid_dates as p on p.invoice_id = i.invoice_id
)
select
    c.customer_id,
    c.customer_name,
    c.customer_group,
    c.territory,
    c.email,
    min(i.invoice_date) as first_invoice_date,
    max(i.invoice_date) as last_invoice_date,
    count(i.invoice_id) as invoices,
    coalesce(sum(i.net_total), 0) as lifetime_revenue,
    count(i.invoice_id) filter (where i.is_paid) as invoices_paid,
    round(avg(i.paid_date - i.invoice_date) filter (where i.is_paid), 1) as avg_days_to_pay,
    round(
        100.0 * count(i.invoice_id) filter (where i.is_paid and i.paid_date > i.due_date)
        / nullif(count(i.invoice_id) filter (where i.is_paid), 0),
        1
    ) as pct_paid_late,
    coalesce(sum(i.outstanding_amount), 0) as open_balance,
    coalesce(sum(i.outstanding_amount) filter (where i.due_date < {{ as_of_date() }}), 0) as overdue_balance
from {{ ref('stg_customers') }} as c
left join invoices as i on i.customer_id = c.customer_id
group by c.customer_id, c.customer_name, c.customer_group, c.territory, c.email
