-- Every invoice's lines must add up to its net total (to the cent).
select i.invoice_id, i.net_total, sum(l.net_amount) as lines_total
from {{ ref('stg_sales_invoices') }} as i
join {{ ref('stg_sales_invoice_lines') }} as l on l.invoice_id = i.invoice_id
group by i.invoice_id, i.net_total
having abs(i.net_total - sum(l.net_amount)) > 0.005
