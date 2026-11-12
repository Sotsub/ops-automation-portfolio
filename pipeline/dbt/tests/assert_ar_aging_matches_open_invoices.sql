-- The aging summary must account for every open invoice and every dollar outstanding.
select a.invoices, a.amount, o.invoices as open_invoices, o.amount as open_amount
from (select sum(invoices) as invoices, sum(outstanding_amount) as amount from {{ ref('ar_aging') }}) as a
cross join (
    select count(*) as invoices, sum(outstanding_amount) as amount
    from {{ ref('stg_sales_invoices') }}
    where outstanding_amount > 0
) as o
where a.invoices <> o.invoices or abs(a.amount - o.amount) > 0.005
