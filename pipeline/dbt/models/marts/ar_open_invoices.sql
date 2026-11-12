-- Unpaid sales invoices with how overdue they are on the as-of date. Demo data only.
with open_invoices as (
    select
        i.invoice_id,
        i.customer_id,
        c.customer_name,
        c.customer_group,
        c.territory,
        i.invoice_date,
        i.due_date,
        i.grand_total as invoice_amount,
        i.outstanding_amount,
        greatest({{ as_of_date() }} - i.due_date, 0) as days_overdue
    from {{ ref('stg_sales_invoices') }} as i
    left join {{ ref('stg_customers') }} as c on c.customer_id = i.customer_id
    where i.outstanding_amount > 0
)
select
    *,
    case
        when days_overdue = 0 then 'Current'
        when days_overdue <= 30 then '1-30 days'
        when days_overdue <= 60 then '31-60 days'
        when days_overdue <= 90 then '61-90 days'
        else 'Over 90 days'
    end as aging_bucket,
    {{ as_of_date() }} as as_of_date
from open_invoices
