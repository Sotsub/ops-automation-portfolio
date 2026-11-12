"""ErpClient and the integration-user helpers, tested against a fake HTTP server (no ERPNext)."""

import json

import httpx
import pytest

from erp import api_user
from erp.client import PAGE_SIZE, ErpClient, ErpError
from shared.config import Settings


def make_client(handler) -> ErpClient:
    return ErpClient(
        "http://erp.test", "key123", "secret456", retries=2, transport=httpx.MockTransport(handler)
    )


def test_token_header_and_paging():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        start = int(request.url.params["limit_start"])
        total = PAGE_SIZE + 3
        rows = [{"name": f"R{i}"} for i in range(start, min(start + PAGE_SIZE, total))]
        return httpx.Response(200, json={"data": rows})

    with make_client(handler) as client:
        rows = client.get_list("Sales Order", filters=[["docstatus", "=", 1]])
    assert len(rows) == PAGE_SIZE + 3
    assert len(seen) == 2, "a full page must trigger a second request"
    assert seen[0].headers["Authorization"] == "token key123:secret456"
    assert seen[0].url.raw_path.decode().split("?")[0] == "/api/resource/Sales%20Order"
    assert seen[0].url.params["limit_page_length"] == str(PAGE_SIZE)
    assert json.loads(seen[0].url.params["filters"]) == [["docstatus", "=", 1]]


def test_names_with_slashes_are_escaped():
    paths = []

    def handler(request):
        paths.append(request.url.raw_path.decode())
        return httpx.Response(200, json={"data": {"name": "x"}})

    with make_client(handler) as client:
        client.get_doc("Account", "Bank / Cash - BSC")
    assert paths == ["/api/resource/Account/Bank%20%2F%20Cash%20-%20BSC"]


def test_server_messages_become_a_readable_error():
    def handler(request):
        body = {
            "exc_type": "ValidationError",
            "_server_messages": json.dumps([json.dumps({"message": "Qty must be positive"})]),
        }
        return httpx.Response(417, json=body)

    with make_client(handler) as client, pytest.raises(ErpError) as err:
        client.insert({"doctype": "Item", "item_code": "X"})
    assert err.value.status == 417
    assert err.value.exc_type == "ValidationError"
    assert "Qty must be positive" in str(err.value)


def test_get_is_retried_on_server_error_but_insert_is_not(monkeypatch):
    monkeypatch.setattr("erp.client.time.sleep", lambda _: None)
    calls = {"GET": 0, "POST": 0}

    def handler(request):
        calls[request.method] += 1
        if request.method == "GET" and calls["GET"] == 1:
            return httpx.Response(502, text="bad gateway")
        if request.method == "POST":
            return httpx.Response(504, text="timeout")
        return httpx.Response(200, json={"message": "integration@example.com"})

    with make_client(handler) as client:
        assert client.logged_user() == "integration@example.com"
        with pytest.raises(ErpError):
            client.insert({"doctype": "Item"})
    assert calls == {"GET": 2, "POST": 1}, (
        "a POST that timed out may have saved, so never resend it"
    )


def test_submit_saves_docstatus_one():
    sent = []

    def handler(request):
        sent.append((request.method, request.url.raw_path.decode(), json.loads(request.content)))
        return httpx.Response(200, json={"data": {"name": "SO-1", "docstatus": 1}})

    with make_client(handler) as client:
        assert client.submit("Sales Order", "SO-1")["docstatus"] == 1
    assert sent == [("PUT", "/api/resource/Sales%20Order/SO-1", {"docstatus": 1})]


# ---------------------------------------------------------------- api_user


def test_set_env_values_replaces_and_appends(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\nERPNEXT_API_KEY=\n# note\nB=2\n", encoding="utf-8")
    env.chmod(0o600)
    api_user.set_env_values(env, {"ERPNEXT_API_KEY": "k", "ERPNEXT_API_SECRET": "s"})
    assert (
        env.read_text(encoding="utf-8")
        == "A=1\nERPNEXT_API_KEY=k\n# note\nB=2\nERPNEXT_API_SECRET=s\n"
    )
    assert env.stat().st_mode & 0o777 == 0o600, "keep .env's permissions"


def fake_erpnext(user_exists: bool, roles: list[str]):
    """A tiny stand-in for ERPNext's user endpoints. Records every request."""
    log = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        log.append((request.method, request.url.path, body))
        path = request.url.path
        if path == "/api/method/login":
            return httpx.Response(200, json={"message": "Logged In"})
        if path == f"/api/resource/User/{api_user.API_USER}" and request.method == "GET":
            if not user_exists:
                return httpx.Response(404, json={})
            return httpx.Response(200, json={"data": {"roles": [{"role": r} for r in roles]}})
        if path.startswith("/api/resource/User"):
            return httpx.Response(200, json={"data": {}})
        if path.endswith("generate_keys"):
            return httpx.Response(
                200, json={"message": {"api_key": "new-key", "api_secret": "new-secret"}}
            )
        return httpx.Response(404, json={})

    return httpx.MockTransport(handler), log


def settings_with_password() -> Settings:
    return Settings(_env_file=None, erpnext_url="http://erp.test", erpnext_admin_password="pw")


def test_ensure_user_creates_missing_user_with_all_roles():
    transport, log = fake_erpnext(user_exists=False, roles=[])
    http = api_user.admin_session(settings_with_password(), transport)
    added = api_user.ensure_user(http)
    assert added == api_user.API_USER_ROLES
    create = next(
        body for method, path, body in log if method == "POST" and path == "/api/resource/User"
    )
    assert create["email"] == api_user.API_USER
    assert create["send_welcome_email"] == 0


def test_ensure_user_adds_only_missing_roles_and_keeps_others():
    transport, log = fake_erpnext(user_exists=True, roles=["System Manager", "Some Other Role"])
    http = api_user.admin_session(settings_with_password(), transport)
    added = api_user.ensure_user(http)
    assert "System Manager" not in added and "Sales Master Manager" in added
    put = next(body for method, _, body in log if method == "PUT")
    sent = [row["role"] for row in put["roles"]]
    assert sent[:2] == ["System Manager", "Some Other Role"], (
        "PUT replaces the table, so keep existing roles"
    )
    assert set(api_user.API_USER_ROLES) <= set(sent)


def test_create_key_returns_env_values():
    transport, _ = fake_erpnext(user_exists=True, roles=api_user.API_USER_ROLES)
    http = api_user.admin_session(settings_with_password(), transport)
    assert api_user.create_key(http) == {
        "ERPNEXT_API_KEY": "new-key",
        "ERPNEXT_API_SECRET": "new-secret",
    }


def test_missing_admin_password_stops_with_a_hint():
    with pytest.raises(SystemExit, match="make env-secrets"):
        api_user.admin_session(Settings(_env_file=None, erpnext_admin_password=None))
