"""Live checks for the Metabase dashboards (needs `make up-reporting`, `make pipeline-run`).

Run with `make dashboards-check`. The figures Metabase shows must equal marts.kpi_summary.
"""

from collections import Counter

import httpx
import psycopg
import pytest

from pipeline import dashboards as d
from pipeline import metabase_setup
from shared.config import Settings

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def settings():
    s = Settings()
    if not (s.metabase_admin_password and s.postgres_password):
        pytest.fail("METABASE_ADMIN_PASSWORD or POSTGRES_PASSWORD missing in .env.")
    return s


@pytest.fixture(scope="module")
def mb(settings):
    assert metabase_setup.main() == 0, "make dashboards failed; see the JSON log above"
    client = httpx.Client(base_url=f"http://localhost:{settings.metabase_port}", timeout=120)
    session = client.post(
        "/api/session",
        json={
            "username": settings.metabase_admin_email,
            "password": settings.metabase_admin_password.get_secret_value(),
        },
    ).json()["id"]
    client.headers["X-Metabase-Session"] = session
    yield client
    client.close()


@pytest.fixture(scope="module")
def items(mb):
    collections = [c for c in mb.get("/api/collection").json() if c.get("name") == d.COLLECTION]
    assert len(collections) == 1
    return mb.get(f"/api/collection/{collections[0]['id']}/items").json()["data"]


@pytest.fixture(scope="module")
def kpi(settings):
    with psycopg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password.get_secret_value(),
    ) as conn:
        cur = conn.execute("select * from marts.kpi_summary")
        return dict(zip([c.name for c in cur.description], cur.fetchone(), strict=True))


def test_everything_exists_once(items):
    counts = Counter((i["model"], i["name"]) for i in items)
    assert all(n == 1 for n in counts.values()), counts
    assert {name for model, name in counts if model == "card"} == {c.name for c in d.CARDS}
    assert {name for model, name in counts if model == "dashboard"} == {
        x.name for x in d.DASHBOARDS
    }


def test_metabase_reads_only_marts_as_reporting_reader(mb):
    db = next(x for x in mb.get("/api/database").json()["data"] if x["name"] == d.DATABASE_NAME)
    assert db["details"]["user"] == "reporting_reader"
    tables = mb.get(f"/api/database/{db['id']}/metadata").json()["tables"]
    assert {t["schema"] for t in tables} == {"marts"}


@pytest.mark.parametrize(
    "card, column",
    [
        ("Revenue", "revenue"),
        ("Gross margin %", "gross_margin_pct"),
        ("Open receivables", "open_receivables"),
        ("Overdue receivables", "overdue_receivables"),
        ("Overdue invoices", "overdue_invoices"),
        ("Open payables", "open_payables"),
        ("Items below reorder level", "items_below_reorder"),
    ],
)
def test_headline_numbers_equal_the_marts(mb, items, kpi, card, column):
    card_id = next(i["id"] for i in items if i["model"] == "card" and i["name"] == card)
    shown = mb.post(f"/api/card/{card_id}/query").json()["data"]["rows"][0][0]
    assert float(shown) == pytest.approx(float(kpi[column]), abs=0.005)
