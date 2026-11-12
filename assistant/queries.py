"""The approved queries the AI assistant may run. Demo data only.

The model never writes SQL. It picks one of these queries and suggests parameter values. Each
value is checked here (type, range, fixed list of choices), and the SQL is fixed text in this file
with values passed as bind parameters. Choices that change the SQL itself, such as which column to
rank by, map to fixed SQL fragments, never to text from the model.

Every query reads the approved views in the `ai` schema, which ai_reader is limited to.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from erp import seed_data as sd

CUSTOMER_GROUPS = tuple(sd.CUSTOMERS)
REGIONS = sd.TERRITORIES
PRODUCT_GROUPS = tuple(sd.ITEM_GROUPS)
MAX_ROWS = 100


class InvalidArguments(ValueError):
    """The model asked for a query with arguments that aren't allowed. Sent back to the model."""


@dataclass(frozen=True)
class Param:
    name: str
    kind: str  # "integer", "string", "month" (YYYY-MM), "choice"
    description: str
    choices: tuple[str, ...] = ()
    minimum: int | None = None
    maximum: int | None = None
    default: Any = None
    required: bool = False

    def schema(self) -> dict[str, Any]:
        """JSON schema for the model's tool declaration."""
        if self.kind == "integer":
            spec: dict[str, Any] = {"type": "integer"}
        elif self.kind == "choice":
            spec = {"type": "string", "enum": list(self.choices)}
        else:
            spec = {"type": "string"}
        description = self.description
        if self.kind == "month":
            description += " Format YYYY-MM."
        if self.default is not None:
            description += f" Default {self.default}."
        spec["description"] = description
        return spec

    def check(self, value: Any) -> Any:
        if value is None or value == "":
            if self.required:
                raise InvalidArguments(f"{self.name} is required")
            return self.default
        if self.kind == "integer":
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or int(value) != value
            ):
                raise InvalidArguments(f"{self.name} must be a whole number")
            value = int(value)
            if (self.minimum is not None and value < self.minimum) or (
                self.maximum is not None and value > self.maximum
            ):
                raise InvalidArguments(
                    f"{self.name} must be between {self.minimum} and {self.maximum}"
                )
            return value
        if not isinstance(value, str):
            raise InvalidArguments(f"{self.name} must be text")
        value = value.strip()
        if self.kind == "choice":
            if value not in self.choices:
                raise InvalidArguments(f"{self.name} must be one of: {', '.join(self.choices)}")
            return value
        if self.kind == "month":
            if not re.fullmatch(r"\d{4}-\d{2}", value):
                raise InvalidArguments(f"{self.name} must look like 2026-03")
            try:
                return date(int(value[:4]), int(value[5:]), 1)
            except ValueError as exc:
                raise InvalidArguments(f"{self.name} is not a real month") from exc
        if len(value) > 100:
            raise InvalidArguments(f"{self.name} is too long")
        return value


@dataclass(frozen=True)
class Query:
    name: str
    description: str
    params: tuple[Param, ...]
    build: Callable[[dict[str, Any]], tuple[str, dict[str, Any]]]

    def declaration(self) -> dict[str, Any]:
        """Function declaration in the shape the Gemini REST API expects."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {p.name: p.schema() for p in self.params},
                "required": [p.name for p in self.params if p.required],
            },
        }

    def prepare(self, args: dict[str, Any] | None) -> tuple[str, dict[str, Any], dict[str, Any]]:
        """Check the model's arguments. Returns (sql, bind values, the arguments actually used)."""
        args = dict(args or {})
        unknown = set(args) - {p.name for p in self.params}
        if unknown:
            raise InvalidArguments(f"unknown arguments: {', '.join(sorted(unknown))}")
        used = {p.name: p.check(args.get(p.name)) for p in self.params}
        sql, values = self.build(used)
        return (
            sql,
            values,
            {k: (v.isoformat()[:7] if isinstance(v, date) else v) for k, v in used.items()},
        )


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


START = Param("start_month", "month", "First month to include.")
END = Param("end_month", "month", "Last month to include.")
MONTH_FILTER = (
    "(%(start_month)s::date IS NULL OR {col} >= %(start_month)s::date)"
    " AND (%(end_month)s::date IS NULL OR {col} <= %(end_month)s::date)"
)

RANK_COLUMNS = {
    "lifetime_revenue": "lifetime_revenue",
    "open_balance": "open_balance",
    "overdue_balance": "overdue_balance",
    "pct_paid_late": "pct_paid_late",
    "avg_days_to_pay": "avg_days_to_pay",
}
SALES_DIMENSIONS = {
    "customer_group": "customer_group",
    "region": "region",
    "product_group": "product_group",
}
SPEND_DIMENSIONS = {"supplier": "supplier", "month": "bill_month"}
STOCK_FILTERS = {
    "below_reorder_level": "below_reorder_level",
    "out_of_stock": "on_hand_qty = 0",
    "all_items": "true",
}


def _monthly_sales(a):
    return (
        "SELECT invoice_month, SUM(revenue) AS revenue, SUM(gross_margin) AS gross_margin,\n"
        "  ROUND(100 * SUM(gross_margin) / NULLIF(SUM(revenue), 0), 1) AS gross_margin_pct\n"
        "FROM ai.sales_monthly\n"
        f"WHERE {MONTH_FILTER.format(col='invoice_month')}\n"
        "  AND (%(customer_group)s::text IS NULL OR customer_group = %(customer_group)s)\n"
        "  AND (%(region)s::text IS NULL OR region = %(region)s)\n"
        "  AND (%(product_group)s::text IS NULL OR product_group = %(product_group)s)\n"
        "GROUP BY invoice_month ORDER BY invoice_month",
        a,
    )


def _sales_breakdown(a):
    dim = SALES_DIMENSIONS[a["by"]]
    return (
        f"SELECT {dim}, SUM(revenue) AS revenue, SUM(gross_margin) AS gross_margin,\n"
        "  ROUND(100 * SUM(gross_margin) / NULLIF(SUM(revenue), 0), 1) AS gross_margin_pct,\n"
        "  ROUND(100 * SUM(revenue) / NULLIF(SUM(SUM(revenue)) OVER (), 0), 1) AS revenue_share_pct\n"
        "FROM ai.sales_monthly\n"
        f"WHERE {MONTH_FILTER.format(col='invoice_month')}\n"
        f"GROUP BY {dim} ORDER BY revenue DESC",
        a,
    )


def _rank_customers(a):
    col = RANK_COLUMNS[a["rank_by"]]
    paid_only = "AND invoices_paid > 0" if col in ("pct_paid_late", "avg_days_to_pay") else ""
    return (
        "SELECT customer_name, customer_group, region, invoices, lifetime_revenue, avg_days_to_pay,\n"
        "  pct_paid_late, open_balance, overdue_balance\n"
        "FROM ai.customers\n"
        f"WHERE (%(customer_group)s::text IS NULL OR customer_group = %(customer_group)s) {paid_only}\n"
        f"ORDER BY {col} DESC NULLS LAST, customer_name LIMIT %(limit)s",
        a,
    )


def _customer_profile(a):
    return (
        "SELECT * FROM ai.customers WHERE customer_name ILIKE %(pattern)s ORDER BY customer_name LIMIT 5",
        {"pattern": f"%{_escape_like(a['customer_name'])}%"},
    )


def _overdue_invoices(a):
    customer = a["customer_name"]
    return (
        "SELECT customer_name, invoice_id, invoice_date, due_date, days_overdue, outstanding_amount,\n"
        "  aging_bucket, as_of_date\n"
        "FROM ai.open_invoices\n"
        "WHERE days_overdue >= %(min_days_overdue)s\n"
        "  AND (%(pattern)s::text IS NULL OR customer_name ILIKE %(pattern)s)\n"
        "ORDER BY days_overdue DESC, outstanding_amount DESC",
        {**a, "pattern": f"%{_escape_like(customer)}%" if customer else None},
    )


def _inventory_alerts(a):
    condition = STOCK_FILTERS[a["status"]]
    return (
        "SELECT item_code, item_name, product_group, stock_status, on_hand_qty, reorder_level,\n"
        "  on_order_qty, units_sold_90d, days_of_cover, default_supplier, as_of_date\n"
        "FROM ai.inventory_status\n"
        f"WHERE {condition}\n"
        "  AND (%(product_group)s::text IS NULL OR product_group = %(product_group)s)\n"
        "ORDER BY on_hand_qty = 0 DESC, days_of_cover NULLS FIRST, item_code",
        a,
    )


def _supplier_spend(a):
    dim = SPEND_DIMENSIONS[a["by"]]
    return (
        f"SELECT {dim}, SUM(bills) AS bills, SUM(billed_amount) AS billed_amount,\n"
        "  SUM(outstanding_amount) AS outstanding_amount\n"
        "FROM ai.supplier_spend_monthly\n"
        f"WHERE {MONTH_FILTER.format(col='bill_month')}\n"
        f"GROUP BY {dim} ORDER BY {'bill_month' if dim == 'bill_month' else 'billed_amount DESC'}",
        a,
    )


QUERIES: tuple[Query, ...] = (
    Query(
        "get_kpis",
        "Headline figures: all-time revenue, gross margin and %, number of invoices, open and overdue "
        "receivables, overdue invoice count, open payables, items below reorder level, open orders, "
        "and the as_of_date that overdue days are measured from.",
        (),
        lambda a: ("SELECT * FROM ai.kpi_summary", a),
    ),
    Query(
        "monthly_sales",
        "Revenue, gross margin and margin % per month, optionally for one customer group, region or "
        "product group and a range of months.",
        (
            START,
            END,
            Param("customer_group", "choice", "Only this customer group.", CUSTOMER_GROUPS),
            Param("region", "choice", "Only this sales region.", REGIONS),
            Param("product_group", "choice", "Only this product group.", PRODUCT_GROUPS),
        ),
        _monthly_sales,
    ),
    Query(
        "sales_breakdown",
        "Revenue, gross margin, margin % and each group's share of total revenue (%), split by "
        "customer group, region or product group, optionally for a range of months. Highest first.",
        (
            Param(
                "by", "choice", "What to split sales by.", tuple(SALES_DIMENSIONS), required=True
            ),
            START,
            END,
        ),
        _sales_breakdown,
    ),
    Query(
        "rank_customers",
        "Customers ranked by lifetime revenue, open balance, overdue balance, percent of invoices paid "
        "late, or average days to pay. Use for top customers and for who pays late.",
        (
            Param(
                "rank_by", "choice", "Which measure to rank by.", tuple(RANK_COLUMNS), required=True
            ),
            Param(
                "limit",
                "integer",
                "How many customers to return.",
                minimum=1,
                maximum=20,
                default=5,
            ),
            Param("customer_group", "choice", "Only this customer group.", CUSTOMER_GROUPS),
        ),
        _rank_customers,
    ),
    Query(
        "customer_profile",
        "One customer's group, region, first and last invoice, revenue, payment habits, open and overdue "
        "balance. Matches part of the name.",
        (Param("customer_name", "string", "The customer's name, or part of it.", required=True),),
        _customer_profile,
    ),
    Query(
        "overdue_invoices",
        "Unpaid invoices at least this many days past due, oldest first, optionally for one customer.",
        (
            Param(
                "min_days_overdue",
                "integer",
                "Minimum days past due.",
                minimum=1,
                maximum=365,
                default=1,
            ),
            Param("customer_name", "string", "Only this customer (part of the name is enough)."),
        ),
        _overdue_invoices,
    ),
    Query(
        "receivables_aging",
        "Open receivables per aging bucket (Current, 1-30, 31-60, 61-90, over 90 days past due).",
        (),
        lambda a: (
            "SELECT aging_bucket, invoices, outstanding_amount, as_of_date FROM ai.ar_aging "
            "ORDER BY bucket_order",
            a,
        ),
    ),
    Query(
        "inventory_alerts",
        "Products by stock status: at or below reorder level (default), out of stock, or all items, "
        "with on-hand and on-order quantity, 90-day sales, days of cover and default supplier.",
        (
            Param(
                "status",
                "choice",
                "Which products.",
                tuple(STOCK_FILTERS),
                default="below_reorder_level",
            ),
            Param("product_group", "choice", "Only this product group.", PRODUCT_GROUPS),
        ),
        _inventory_alerts,
    ),
    Query(
        "supplier_spend",
        "Supplier bills: number, amount billed and amount still owed, per supplier or per month, "
        "optionally for a range of months.",
        (
            Param(
                "by",
                "choice",
                "Group by supplier or by month.",
                tuple(SPEND_DIMENSIONS),
                required=True,
            ),
            START,
            END,
        ),
        _supplier_spend,
    ),
)

BY_NAME = {q.name: q for q in QUERIES}
