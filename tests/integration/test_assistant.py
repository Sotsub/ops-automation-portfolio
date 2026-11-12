"""Live checks for the assistant's data access, no AI model needed (`make assistant-check`).

Needs Postgres with the pipeline already run (`make up`, `make pipeline-run`).
"""

from decimal import Decimal

import psycopg
import pytest

from assistant.ask import connect_ai_reader, run_query
from assistant.llm import ToolCall
from assistant.queries import QUERIES
from pipeline import db
from shared.config import Settings

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def settings():
    s = Settings()
    if not (s.ai_reader_password and s.postgres_password):
        pytest.fail("AI_READER_PASSWORD or POSTGRES_PASSWORD missing in .env.")
    return s


@pytest.fixture(scope="module")
def reader(settings):
    with connect_ai_reader(settings) as conn:
        yield conn


@pytest.fixture(scope="module")
def kpi(settings):
    with db.connect(settings) as admin:
        cur = admin.execute("select * from marts.kpi_summary")
        return dict(zip([c.name for c in cur.description], cur.fetchone(), strict=True))


def default_args(query):
    return {p.name: p.choices[0] for p in query.params if p.required and p.choices} | {
        p.name: "Oak Valley" for p in query.params if p.required and p.kind == "string"
    }


@pytest.mark.parametrize("query", QUERIES, ids=lambda q: q.name)
def test_every_approved_query_runs_as_ai_reader(reader, query):
    run = run_query(reader, ToolCall(query.name, default_args(query)))
    assert run.error is None, run.error
    assert run.row_count > 0


def test_headline_figures_match_the_marts(reader, kpi):
    rows = run_query(reader, ToolCall("get_kpis", {})).result["rows"]
    assert Decimal(str(rows[0]["revenue"])) == kpi["revenue"]
    assert Decimal(str(rows[0]["overdue_receivables"])) == kpi["overdue_receivables"]


def test_overdue_invoices_add_up_to_the_overdue_total(reader, kpi):
    rows = run_query(reader, ToolCall("overdue_invoices", {})).result["rows"]
    assert len(rows) == kpi["overdue_invoices"]
    assert (
        round(sum(Decimal(str(r["outstanding_amount"])) for r in rows), 2)
        == kpi["overdue_receivables"]
    )


def test_sales_breakdown_shares_add_to_100(reader, kpi):
    rows = run_query(reader, ToolCall("sales_breakdown", {"by": "region"})).result["rows"]
    assert round(sum(Decimal(str(r["revenue"])) for r in rows), 2) == kpi["revenue"]
    assert abs(sum(r["revenue_share_pct"] for r in rows) - 100) < 0.3


def test_ai_reader_can_only_read_the_ai_views(reader):
    assert reader.execute("select count(*) from ai.customers").fetchone()[0] == 40
    for statement in (
        "select 1 from marts.customers limit 1",
        "select 1 from raw.erpnext_customer limit 1",
        "select 1 from staging.stg_customers limit 1",
        "select 1 from ops.assistant_log limit 1",
        "select email from ai.customers limit 1",
        "update ai.customers set open_balance = 0",
        "create table ai.should_fail (a int)",
    ):
        with pytest.raises(psycopg.Error):
            reader.execute(statement)


def test_long_queries_are_stopped(reader):
    with pytest.raises(psycopg.errors.QueryCanceled):
        reader.execute("select pg_sleep(10)")
