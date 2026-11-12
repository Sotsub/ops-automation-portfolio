-- Monthly totals must equal the line-level totals they summarise.
select m.revenue, l.revenue as lines_revenue
from (select sum(revenue) as revenue from {{ ref('sales_monthly') }}) as m
cross join (select sum(revenue) as revenue from {{ ref('sales_lines') }}) as l
where abs(m.revenue - l.revenue) > 0.005
