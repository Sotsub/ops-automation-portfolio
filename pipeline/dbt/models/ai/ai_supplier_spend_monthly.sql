-- Approved for the AI assistant: supplier bills per month. Demo data only.
{{ config(alias='supplier_spend_monthly') }}
select bill_month, supplier_id as supplier, supplier_group, bills, billed_amount, outstanding_amount
from {{ ref('supplier_spend_monthly') }}
