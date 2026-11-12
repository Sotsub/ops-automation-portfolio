"""Live checks for the ERP-to-reporting pipeline (Project 1).

Needs ERPNext (`make erp-up`, seeded) and Postgres (`make up`). Run with `make pipeline-check`.
Each check compares numbers built in SQL (marts) with figures read fresh from ERPNext's API.
Credentials come from .env and are never printed.
"""

from datetime import date
from decimal import Decimal

import psycopg
import pytest

from erp.client import ErpClient
from pipeline import run
from pipeline.entities import PARENTS
from shared.config import Settings

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def settings():
    s = Settings()
    if not (s.postgres_password and s.erpnext_api_key and s.reporting_reader_password):
        pytest.fail(
            "POSTGRES_PASSWORD, ERPNEXT_API_KEY or REPORTING_READER_PASSWORD missing in .env."
        )
    return s


@pytest.fixture(scope="module")
def pipeline_run(settings):
    """Run the pipeline once (incremental load + dbt build) for this module's checks."""
    assert run.main([]) == 0, "pipeline run failed; see the JSON log above"


@pytest.fixture(scope="module")
def admin(settings, pipeline_run):
    with psycopg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password.get_secret_value(),
        autocommit=True,
    ) as conn:
        yield conn


@pytest.fixture(scope="module")
def erp(settings):
    with ErpClient(
        settings.erpnext_url,
        settings.erpnext_api_key.get_secret_value(),
        settings.erpnext_api_secret.get_secret_value(),
    ) as client:
        yield client


@pytest.fixture(scope="module")
def kpi(admin):
    cur = admin.execute("select * from marts.kpi_summary")
    names = [c.name for c in cur.description]
    return dict(zip(names, cur.fetchone(), strict=True))


def money(rows, field):
    return round(sum(Decimal(str(r[field])) for r in rows), 2)


def test_last_run_succeeded_and_was_recorded(admin):
    status, mode, rows = admin.execute(
        "select status, mode, rows_loaded from ops.pipeline_runs order by started_at desc limit 1"
    ).fetchone()
    assert (status, mode) == ("succeeded", "incremental")
    assert rows["dbt"].get("error", 0) == 0 and rows["dbt"].get("fail", 0) == 0


def test_raw_has_every_erpnext_record(admin, erp):
    for entity in PARENTS:
        in_erpnext = {r["name"] for r in erp.get_list(entity.doctype)}
        in_raw = {r[0] for r in admin.execute(f"select name from raw.{entity.table}")}
        assert in_erpnext <= in_raw, f"{entity.doctype}: {len(in_erpnext - in_raw)} missing"


def test_revenue_and_receivables_match_erpnext(kpi, erp):
    invoices = erp.get_list(
        "Sales Invoice",
        fields=["grand_total", "outstanding_amount", "due_date"],
        filters=[["docstatus", "=", 1]],
    )
    assert kpi["invoices"] == len(invoices)
    assert kpi["revenue"] == money(invoices, "grand_total")
    assert kpi["open_receivables"] == money(invoices, "outstanding_amount")
    as_of = kpi["as_of_date"].isoformat()
    overdue = [r for r in invoices if r["outstanding_amount"] > 0 and r["due_date"] < as_of]
    assert kpi["overdue_invoices"] == len(overdue)
    assert kpi["overdue_receivables"] == money(overdue, "outstanding_amount")


def test_gross_margin_matches_erpnext_cost_of_goods_sold(kpi, erp):
    gl = erp.get_list(
        "GL Entry",
        fields=["account", "debit", "credit"],
        filters=[
            ["is_cancelled", "=", 0],
            ["account", "in", ["Sales - BSC", "Cost of Goods Sold - BSC"]],
        ],
    )
    sales = sum(
        Decimal(str(g["credit"])) - Decimal(str(g["debit"]))
        for g in gl
        if g["account"] == "Sales - BSC"
    )
    cogs = sum(
        Decimal(str(g["debit"])) - Decimal(str(g["credit"]))
        for g in gl
        if g["account"] != "Sales - BSC"
    )
    assert kpi["revenue"] == round(sales, 2)
    assert kpi["gross_margin"] == round(sales - cogs, 2)


def test_payables_match_erpnext(kpi, erp):
    bills = erp.get_list(
        "Purchase Invoice", fields=["outstanding_amount"], filters=[["docstatus", "=", 1]]
    )
    assert kpi["open_payables"] == money(bills, "outstanding_amount")


def test_low_stock_matches_erpnext(admin, erp):
    bins = {
        b["item_code"]: b["actual_qty"]
        for b in erp.get_list("Bin", fields=["item_code", "actual_qty"])
    }
    levels = {
        r["parent"]: r["warehouse_reorder_level"]
        for r in erp.get_list(
            "Item Reorder", fields=["parent", "warehouse_reorder_level"], parent="Item"
        )
    }
    expected = {code for code, level in levels.items() if bins.get(code, 0) <= level}
    marts = {
        r[0]
        for r in admin.execute(
            "select item_code from marts.inventory_status where below_reorder_level"
        )
    }
    assert marts == expected


def test_reporting_reader_can_only_read_marts(settings, pipeline_run):
    with psycopg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user="reporting_reader",
        password=settings.reporting_reader_password.get_secret_value(),
        autocommit=True,
    ) as conn:
        assert conn.execute("select count(*) from marts.kpi_summary").fetchone() == (1,)
        for statement in (
            "select 1 from raw.erpnext_customer limit 1",
            "select 1 from staging.stg_customers limit 1",
            "select 1 from ops.pipeline_runs limit 1",
            "update marts.customers set open_balance = 0",
            "create table marts.should_fail (a int)",
        ):
            with pytest.raises(psycopg.Error):
                conn.execute(statement)


def test_as_of_date_is_today_by_default(kpi):
    assert kpi["as_of_date"] == date.today()
