"""Metabase questions and dashboards for Project 1, defined as data. Demo data only.

Every question is SQL over the marts schema, which dbt builds. Questions only select, sort and
total figures that dbt already calculated, so the numbers on screen are the tested numbers.
`pipeline/metabase_setup.py` creates or updates all of this in Metabase.
"""

from dataclasses import dataclass, field
from typing import Any

COLLECTION = "Bluefield Supply Co. (demo)"
DATABASE_NAME = "Bluefield reporting (demo)"
DEMO_NOTE = (
    "**Demo data.** Bluefield Supply Co. and everything here is fictional. Numbers come from the "
    "`marts` tables that dbt builds from ERPNext and tests on every pipeline run."
)


def money(*columns: str) -> dict[str, Any]:
    """Visualization settings that show the given columns as US dollars."""
    return {
        "column_settings": {
            f'["name","{c}"]': {"number_style": "currency", "currency": "USD", "decimals": 0}
            for c in columns
        }
    }


@dataclass(frozen=True)
class Card:
    name: str
    sql: str
    display: str  # scalar, line, bar, row, pie, table
    description: str = ""
    viz: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Placement:
    card: str | None  # card name, or None for a text box
    row: int
    col: int
    size_x: int
    size_y: int
    text: str = ""


@dataclass(frozen=True)
class Dashboard:
    name: str
    description: str
    layout: tuple[Placement, ...]


CARDS: tuple[Card, ...] = (
    # --- headline numbers -----------------------------------------------------------------------
    Card("Revenue", "SELECT revenue FROM marts.kpi_summary", "scalar",
         "Invoiced sales before tax, all time.", money("revenue")),
    Card("Gross margin %", "SELECT gross_margin_pct FROM marts.kpi_summary", "scalar",
         "Revenue minus cost of goods at ERPNext's valuation, as a share of revenue.",
         {"column_settings": {'["name","gross_margin_pct"]': {"suffix": "%"}}}),
    Card("Invoices", "SELECT invoices FROM marts.kpi_summary", "scalar", "Submitted sales invoices."),
    Card("Open receivables", "SELECT open_receivables FROM marts.kpi_summary", "scalar",
         "Unpaid customer invoices, due or not.", money("open_receivables")),
    Card("Overdue receivables", "SELECT overdue_receivables FROM marts.kpi_summary", "scalar",
         "Unpaid customer invoices past their due date.", money("overdue_receivables")),
    Card("Overdue invoices", "SELECT overdue_invoices FROM marts.kpi_summary", "scalar",
         "Number of unpaid invoices past their due date."),
    Card("Open payables", "SELECT open_payables FROM marts.kpi_summary", "scalar",
         "Unpaid supplier bills.", money("open_payables")),
    Card("Items below reorder level", "SELECT items_below_reorder FROM marts.kpi_summary", "scalar",
         "Products with stock on hand at or below their reorder level."),
    Card("Data as of",
         "SELECT as_of_date, data_loaded_at, built_at FROM marts.kpi_summary", "table",
         "as_of_date: the date overdue days are measured from. data_loaded_at: last ERPNext load."),
    # --- sales ----------------------------------------------------------------------------------
    Card("Monthly revenue and gross margin",
         "SELECT invoice_month, SUM(revenue) AS revenue, SUM(gross_margin) AS gross_margin\n"
         "FROM marts.sales_monthly GROUP BY invoice_month ORDER BY invoice_month",
         "line", "Revenue and gross margin per month.",
         {"graph.dimensions": ["invoice_month"], "graph.metrics": ["revenue", "gross_margin"],
          **money("revenue", "gross_margin")}),
    Card("Revenue by customer group",
         "SELECT customer_group, SUM(revenue) AS revenue FROM marts.sales_monthly\n"
         "GROUP BY customer_group ORDER BY revenue DESC",
         "row", "", {"graph.dimensions": ["customer_group"], "graph.metrics": ["revenue"],
                     **money("revenue")}),
    Card("Revenue by region",
         "SELECT territory AS region, SUM(revenue) AS revenue FROM marts.sales_monthly\n"
         "GROUP BY territory ORDER BY revenue DESC",
         "row", "", {"graph.dimensions": ["region"], "graph.metrics": ["revenue"], **money("revenue")}),
    Card("Revenue and margin by product group",
         "SELECT item_group AS product_group, SUM(revenue) AS revenue, SUM(gross_margin) AS gross_margin,\n"
         "  ROUND(100 * SUM(gross_margin) / NULLIF(SUM(revenue), 0), 1) AS gross_margin_pct\n"
         "FROM marts.sales_monthly GROUP BY item_group ORDER BY revenue DESC",
         "table", "", money("revenue", "gross_margin")),
    Card("Top 10 customers",
         "SELECT customer_name, customer_group, territory AS region, invoices, lifetime_revenue,\n"
         "  avg_days_to_pay, pct_paid_late, open_balance\n"
         "FROM marts.customers ORDER BY lifetime_revenue DESC LIMIT 10",
         "table", "Customers by revenue, with how they pay.", money("lifetime_revenue", "open_balance")),
    # --- cash and inventory ---------------------------------------------------------------------
    Card("Receivables aging",
         "SELECT aging_bucket, outstanding_amount, invoices FROM marts.ar_aging ORDER BY bucket_order",
         "bar", "Unpaid invoices by days past due.",
         {"graph.dimensions": ["aging_bucket"], "graph.metrics": ["outstanding_amount"],
          **money("outstanding_amount")}),
    Card("Overdue invoices to chase",
         "SELECT customer_name, invoice_id, invoice_date, due_date, days_overdue, outstanding_amount\n"
         "FROM marts.ar_open_invoices WHERE days_overdue > 0\n"
         "ORDER BY days_overdue DESC, outstanding_amount DESC",
         "table", "Every unpaid invoice past its due date, oldest first.", money("outstanding_amount")),
    Card("Customers who pay late most often",
         "SELECT customer_name, customer_group, invoices_paid, pct_paid_late, avg_days_to_pay,\n"
         "  overdue_balance\n"
         "FROM marts.customers WHERE invoices_paid > 0\n"
         "ORDER BY pct_paid_late DESC, avg_days_to_pay DESC LIMIT 10",
         "table", "", money("overdue_balance")),
    Card("Items to reorder",
         "SELECT item_code, item_name, stock_status, on_hand_qty, reorder_level, on_order_qty,\n"
         "  units_sold_90d, days_of_cover, default_supplier\n"
         "FROM marts.inventory_status WHERE below_reorder_level\n"
         "ORDER BY on_hand_qty = 0 DESC, days_of_cover NULLS FIRST",
         "table", "Products at or below their reorder level. Out-of-stock items first."),
    Card("Supplier spend by month",
         "SELECT bill_month, SUM(billed_amount) AS billed_amount FROM marts.supplier_spend_monthly\n"
         "GROUP BY bill_month ORDER BY bill_month",
         "bar", "Supplier bills received per month.",
         {"graph.dimensions": ["bill_month"], "graph.metrics": ["billed_amount"],
          **money("billed_amount")}),
)  # fmt: skip


def _scalars(names: list[str], row: int) -> list[Placement]:
    width = 24 // len(names)
    return [Placement(name, row, i * width, width, 3) for i, name in enumerate(names)]


DASHBOARDS: tuple[Dashboard, ...] = (
    Dashboard(
        "Sales Overview (demo)",
        "Revenue, margin, customers and product mix for Bluefield Supply Co. Demo data only.",
        (
            Placement(None, 0, 0, 24, 2, DEMO_NOTE),
            *_scalars(["Revenue", "Gross margin %", "Invoices"], 2),
            Placement("Monthly revenue and gross margin", 5, 0, 24, 7),
            Placement("Revenue by customer group", 12, 0, 12, 6),
            Placement("Revenue by region", 12, 12, 12, 6),
            Placement("Revenue and margin by product group", 18, 0, 24, 5),
            Placement("Top 10 customers", 23, 0, 24, 7),
            Placement("Data as of", 30, 0, 24, 3),
        ),
    ),
    Dashboard(
        "Cash and Inventory (demo)",
        "What customers owe, who pays late, what Bluefield owes, and what to reorder. Demo data only.",
        (
            Placement(None, 0, 0, 24, 2, DEMO_NOTE),
            *_scalars(["Open receivables", "Overdue receivables", "Overdue invoices"], 2),
            *_scalars(["Open payables", "Items below reorder level"], 5),
            Placement("Receivables aging", 8, 0, 12, 6),
            Placement("Supplier spend by month", 8, 12, 12, 6),
            Placement("Overdue invoices to chase", 14, 0, 24, 7),
            Placement("Customers who pay late most often", 21, 0, 24, 7),
            Placement("Items to reorder", 28, 0, 24, 8),
            Placement("Data as of", 36, 0, 24, 3),
        ),
    ),
)
