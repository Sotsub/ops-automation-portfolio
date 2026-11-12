"""Create or update the Project 1 dashboards in Metabase (`make dashboards`). Safe to rerun.

1. First run only: complete Metabase's setup with the admin login from .env
   (METABASE_ADMIN_EMAIL / METABASE_ADMIN_PASSWORD). Later runs sign in with it.
2. Connect Metabase to the reporting database as reporting_reader, limited to the marts schema.
3. Create or update each question and dashboard in pipeline/dashboards.py, matched by name
   inside the "Bluefield Supply Co. (demo)" collection.

Endpoints and request shapes follow the OpenAPI spec that Metabase v0.64 serves at
/api/docs/openapi.json. No password is ever printed.
"""

import sys
from typing import Any

import httpx

from pipeline import dashboards as d
from shared.config import Settings
from shared.logging import get_logger, new_run_id

# Metabase runs inside the Compose network, so it reaches Postgres by its service name.
DB_HOST_FROM_METABASE = "postgres"


class MetabaseError(Exception):
    pass


class Metabase:
    def __init__(self, base_url: str, transport: httpx.BaseTransport | None = None):
        self.http = httpx.Client(base_url=base_url.rstrip("/"), timeout=120, transport=transport)

    def close(self) -> None:
        self.http.close()

    def call(self, method: str, path: str, json: Any = None, params: dict | None = None) -> Any:
        response = self.http.request(method, path, json=json, params=params)
        if response.is_error:
            raise MetabaseError(
                f"{method} {path}: HTTP {response.status_code}: {response.text[:300]}"
            )
        return response.json() if response.content else None

    def sign_in(self, email: str, password: str) -> str:
        """Finish first-run setup if needed, otherwise log in. Returns 'setup' or 'login'."""
        props = self.call("GET", "/api/session/properties")
        if not props.get("has-user-setup"):
            session = self.call(
                "POST",
                "/api/setup",
                json={
                    "token": props["setup-token"],
                    "user": {
                        "email": email,
                        "password": password,
                        "first_name": "Bluefield",
                        "last_name": "Admin (demo)",
                    },
                    "prefs": {"site_name": "Bluefield Supply Co. (demo)"},
                },
            )
            how = "setup"
        else:
            session = self.call(
                "POST", "/api/session", json={"username": email, "password": password}
            )
            how = "login"
        self.http.headers["X-Metabase-Session"] = session["id"]
        return how


def ensure_database(mb: Metabase, settings: Settings) -> int:
    if settings.reporting_reader_password is None:
        raise SystemExit("REPORTING_READER_PASSWORD is blank in .env. Run `make env-secrets`.")
    details = {
        "host": DB_HOST_FROM_METABASE,
        "port": 5432,
        "dbname": settings.postgres_db,
        "user": "reporting_reader",
        "password": settings.reporting_reader_password.get_secret_value(),
        "ssl": False,
        "schema-filters-type": "inclusion",
        "schema-filters-patterns": "marts",
    }
    found = mb.call("GET", "/api/database")
    rows = found["data"] if isinstance(found, dict) else found
    existing = next((db for db in rows if db["name"] == d.DATABASE_NAME), None)
    if existing:
        mb.call("PUT", f"/api/database/{existing['id']}", json={"details": details})
        db_id = existing["id"]
    else:
        db_id = mb.call(
            "POST",
            "/api/database",
            json={
                "name": d.DATABASE_NAME,
                "engine": "postgres",
                "details": details,
                "is_full_sync": True,
            },
        )["id"]
    mb.call("POST", f"/api/database/{db_id}/sync_schema")
    return db_id


def ensure_collection(mb: Metabase) -> int:
    for collection in mb.call("GET", "/api/collection"):
        if collection.get("name") == d.COLLECTION and not collection.get("archived"):
            return collection["id"]
    return mb.call(
        "POST",
        "/api/collection",
        json={"name": d.COLLECTION, "description": "Project 1 dashboards. Demo data only."},
    )["id"]


def collection_items(mb: Metabase, collection_id: int, model: str) -> dict[str, int]:
    items = mb.call("GET", f"/api/collection/{collection_id}/items", params={"models": model})
    rows = items["data"] if isinstance(items, dict) else items
    return {item["name"]: item["id"] for item in rows}


def card_payload(card: d.Card, db_id: int, collection_id: int) -> dict[str, Any]:
    return {
        "name": card.name,
        "description": card.description or None,
        "display": card.display,
        "collection_id": collection_id,
        "visualization_settings": card.viz,
        "dataset_query": {
            "database": db_id,
            "type": "native",
            "native": {"query": card.sql, "template-tags": {}},
        },
    }


def ensure_cards(mb: Metabase, db_id: int, collection_id: int) -> dict[str, int]:
    existing = collection_items(mb, collection_id, "card")
    ids = {}
    for card in d.CARDS:
        payload = card_payload(card, db_id, collection_id)
        if card.name in existing:
            mb.call("PUT", f"/api/card/{existing[card.name]}", json=payload)
            ids[card.name] = existing[card.name]
        else:
            ids[card.name] = mb.call("POST", "/api/card", json=payload)["id"]
    return ids


def dashcards(dashboard: d.Dashboard, card_ids: dict[str, int]) -> list[dict[str, Any]]:
    """Every card on the dashboard. Negative ids tell Metabase to create them afresh."""
    cards = []
    for i, place in enumerate(dashboard.layout, start=1):
        dashcard: dict[str, Any] = {
            "id": -i,
            "card_id": card_ids[place.card] if place.card else None,
            "row": place.row,
            "col": place.col,
            "size_x": place.size_x,
            "size_y": place.size_y,
            "parameter_mappings": [],
            "series": [],
            "visualization_settings": {},
        }
        if place.card is None:
            dashcard["visualization_settings"] = {
                "virtual_card": {
                    "name": None,
                    "display": "text",
                    "visualization_settings": {},
                    "dataset_query": {},
                    "archived": False,
                },
                "text": place.text,
            }
        cards.append(dashcard)
    return cards


def ensure_dashboards(mb: Metabase, collection_id: int, card_ids: dict[str, int]) -> dict[str, int]:
    existing = collection_items(mb, collection_id, "dashboard")
    ids = {}
    for dashboard in d.DASHBOARDS:
        dash_id = (
            existing.get(dashboard.name)
            or mb.call(
                "POST",
                "/api/dashboard",
                json={
                    "name": dashboard.name,
                    "collection_id": collection_id,
                    "description": dashboard.description,
                },
            )["id"]
        )
        mb.call(
            "PUT",
            f"/api/dashboard/{dash_id}",
            json={
                "description": dashboard.description,
                "width": "fixed",
                "dashcards": dashcards(dashboard, card_ids),
            },
        )
        ids[dashboard.name] = dash_id
    return ids


def check_cards_run(mb: Metabase, card_ids: dict[str, int]) -> dict[str, int]:
    """Run every question once, so a broken query fails here and not in front of a viewer."""
    rows = {}
    for name, card_id in card_ids.items():
        result = mb.call("POST", f"/api/card/{card_id}/query")
        if result.get("status") != "completed" or result.get("error"):
            raise MetabaseError(f"Question '{name}' failed: {result.get('error')}")
        rows[name] = result["row_count"]
    return rows


def main() -> int:
    settings = Settings()
    log = get_logger("pipeline.metabase_setup", new_run_id(), settings.log_level)
    if settings.metabase_admin_password is None:
        log.error("METABASE_ADMIN_PASSWORD is blank in .env. Run `make env-secrets`.")
        return 1
    mb = Metabase(f"http://localhost:{settings.metabase_port}")
    try:
        how = mb.sign_in(
            settings.metabase_admin_email, settings.metabase_admin_password.get_secret_value()
        )
        db_id = ensure_database(mb, settings)
        collection_id = ensure_collection(mb)
        card_ids = ensure_cards(mb, db_id, collection_id)
        dashboard_ids = ensure_dashboards(mb, collection_id, card_ids)
        row_counts = check_cards_run(mb, card_ids)
    except (MetabaseError, httpx.HTTPError) as exc:
        log.error("Metabase setup failed", extra={"error": str(exc)})
        return 1
    finally:
        mb.close()
    log.info(
        "Dashboards ready",
        extra={
            "signed_in_by": how,
            "database_id": db_id,
            "cards": len(card_ids),
            "dashboards": {name: f"http://localhost:{settings.metabase_port}/dashboard/{i}"
                           for name, i in dashboard_ids.items()},
            "rows_per_question": row_counts,
        },
    )  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
