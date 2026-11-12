"""Dashboard definitions and the Metabase setup script, tested without Metabase."""

import json
import re

import httpx
import pytest

from pipeline import dashboards as d
from pipeline import metabase_setup as ms
from shared.config import Settings

CARD_NAMES = {c.name for c in d.CARDS}


def test_card_names_are_unique():
    assert len(CARD_NAMES) == len(d.CARDS)


@pytest.mark.parametrize("card", d.CARDS, ids=lambda c: c.name)
def test_questions_only_read_marts(card):
    sql = card.sql.upper()
    assert sql.lstrip().startswith("SELECT")
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|GRANT|TRUNCATE)\b", sql)
    tables = re.findall(r"\b(?:FROM|JOIN)\s+([A-Za-z_][\w.]*)", card.sql, re.IGNORECASE)
    assert tables and all(t.lower().startswith("marts.") for t in tables), tables


def test_every_dashboard_card_exists_and_is_labelled_demo():
    for dashboard in d.DASHBOARDS:
        assert "Demo data only." in dashboard.description
        assert "(demo)" in dashboard.name
        texts = [p.text for p in dashboard.layout if p.card is None]
        assert texts and "Demo data" in texts[0], "first card must be the demo-data note"
        for place in dashboard.layout:
            assert place.card is None or place.card in CARD_NAMES, place.card


def test_layouts_fit_the_grid_without_overlapping():
    for dashboard in d.DASHBOARDS:
        taken = set()
        for p in dashboard.layout:
            assert p.col >= 0 and p.col + p.size_x <= 24, (dashboard.name, p)
            cells = {
                (r, c)
                for r in range(p.row, p.row + p.size_y)
                for c in range(p.col, p.col + p.size_x)
            }
            assert not taken & cells, f"{dashboard.name}: {p.card} overlaps another card"
            taken |= cells


def test_every_card_is_used_on_some_dashboard():
    used = {p.card for dash in d.DASHBOARDS for p in dash.layout if p.card}
    assert used == CARD_NAMES


# ---------------------------------------------------------------- setup script vs a fake Metabase


class FakeMetabase:
    """Just enough of Metabase's API to exercise metabase_setup, with state across runs."""

    def __init__(self):
        self.has_user = False
        self.databases: list[dict] = []
        self.collections: list[dict] = []
        self.cards: dict[int, dict] = {}
        self.dashboards: dict[int, dict] = {}
        self.ids = iter(range(10, 10_000))
        self.requests: list[tuple[str, str, dict | None]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        method, path = request.method, request.url.path
        self.requests.append((method, path, body))
        if path == "/api/session/properties":
            return httpx.Response(200, json={"has-user-setup": self.has_user, "setup-token": "tok"})
        if path == "/api/setup":
            assert not self.has_user and body["token"] == "tok"
            self.has_user = True
            return httpx.Response(200, json={"id": "session-1"})
        if path == "/api/session":
            return httpx.Response(200, json={"id": "session-2"})
        assert request.headers.get("X-Metabase-Session"), f"{path} called without signing in"
        if path == "/api/database" and method == "GET":
            return httpx.Response(200, json={"data": self.databases})
        if path == "/api/database" and method == "POST":
            self.databases.append({"id": next(self.ids), **body})
            return httpx.Response(200, json=self.databases[-1])
        if re.fullmatch(r"/api/database/\d+(/sync_schema)?", path):
            return httpx.Response(200, json={})
        if path == "/api/collection" and method == "GET":
            return httpx.Response(200, json=self.collections)
        if path == "/api/collection" and method == "POST":
            self.collections.append({"id": next(self.ids), **body})
            return httpx.Response(200, json=self.collections[-1])
        if m := re.fullmatch(r"/api/collection/(\d+)/items", path):
            store = self.cards if request.url.params["models"] == "card" else self.dashboards
            rows = [{"id": i, "name": c["name"]} for i, c in store.items()]
            return httpx.Response(200, json={"data": rows})
        if path == "/api/card" and method == "POST":
            card_id = next(self.ids)
            self.cards[card_id] = body
            return httpx.Response(200, json={"id": card_id})
        if (m := re.fullmatch(r"/api/card/(\d+)", path)) and method == "PUT":
            self.cards[int(m[1])] = body
            return httpx.Response(200, json={})
        if re.fullmatch(r"/api/card/\d+/query", path):
            return httpx.Response(202, json={"status": "completed", "row_count": 1})
        if path == "/api/dashboard" and method == "POST":
            dash_id = next(self.ids)
            self.dashboards[dash_id] = body
            return httpx.Response(200, json={"id": dash_id})
        if (m := re.fullmatch(r"/api/dashboard/(\d+)", path)) and method == "PUT":
            self.dashboards[int(m[1])].update(body)
            return httpx.Response(200, json={})
        return httpx.Response(404, text=f"unexpected {method} {path}")


def run_setup(fake: FakeMetabase):
    settings = Settings(
        _env_file=None, reporting_reader_password="reader-pw", postgres_db="bluefield"
    )
    mb = ms.Metabase("http://metabase.test", transport=httpx.MockTransport(fake.handler))
    how = mb.sign_in("admin@example.com", "admin-pw")
    db_id = ms.ensure_database(mb, settings)
    collection_id = ms.ensure_collection(mb)
    card_ids = ms.ensure_cards(mb, db_id, collection_id)
    dash_ids = ms.ensure_dashboards(mb, collection_id, card_ids)
    rows = ms.check_cards_run(mb, card_ids)
    return how, card_ids, dash_ids, rows


def test_first_run_sets_up_metabase_and_builds_everything():
    fake = FakeMetabase()
    how, card_ids, dash_ids, rows = run_setup(fake)
    assert how == "setup"
    setup = next(body for _, path, body in fake.requests if path == "/api/setup")
    assert setup["user"]["email"] == "admin@example.com"
    db = fake.databases[0]
    assert db["details"]["user"] == "reporting_reader"
    assert db["details"]["schema-filters-patterns"] == "marts"
    assert db["details"]["host"] == "postgres"
    assert len(fake.cards) == len(d.CARDS) and len(fake.dashboards) == len(d.DASHBOARDS)
    assert set(rows) == CARD_NAMES


def test_second_run_updates_in_place_without_duplicates():
    fake = FakeMetabase()
    _, first_cards, first_dashes, _ = run_setup(fake)
    how, cards, dashes, _ = run_setup(fake)
    assert how == "login"
    assert (cards, dashes) == (first_cards, first_dashes)
    assert len(fake.databases) == 1 and len(fake.collections) == 1
    assert len(fake.cards) == len(d.CARDS) and len(fake.dashboards) == len(d.DASHBOARDS)


def test_cards_are_native_sql_against_the_reporting_database():
    payload = ms.card_payload(d.CARDS[0], db_id=7, collection_id=3)
    assert payload["dataset_query"] == {
        "database": 7,
        "type": "native",
        "native": {"query": d.CARDS[0].sql, "template-tags": {}},
    }
    assert payload["collection_id"] == 3


def test_dashcards_place_text_and_questions():
    dash = d.DASHBOARDS[0]
    ids = {name: n for n, name in enumerate(sorted(CARD_NAMES), start=100)}
    cards = ms.dashcards(dash, ids)
    assert len(cards) == len(dash.layout)
    assert all(c["id"] < 0 for c in cards), "negative ids make Metabase create the dashcards"
    note = cards[0]
    assert note["card_id"] is None and note["visualization_settings"]["text"] == d.DEMO_NOTE


def test_failing_question_stops_the_run():
    def handler(request):
        return httpx.Response(202, json={"status": "failed", "error": "relation does not exist"})

    mb = ms.Metabase("http://metabase.test", transport=httpx.MockTransport(handler))
    with pytest.raises(ms.MetabaseError, match="relation does not exist"):
        ms.check_cards_run(mb, {"Revenue": 1})
