"""Create the ERPNext integration user and store its API key in .env (`make erp-api-keys`).

Safe to rerun. If .env already holds a key that works for this user, nothing changes. Otherwise the
script signs in once as Administrator, creates the user if needed, generates a new key, and writes
ERPNEXT_API_KEY and ERPNEXT_API_SECRET to .env. Neither the password nor the key is ever printed.
"""

import os
import re
import sys
import tempfile
from pathlib import Path

import httpx

from erp.client import ErpClient, ErpError
from shared.config import Settings
from shared.logging import get_logger, new_run_id

API_USER = (
    "integration@example.com"  # example.com is reserved for examples, so it can't reach anyone.
)
API_USER_ROLES = [
    "System Manager",
    "Accounts Manager",
    "Accounts User",
    "Stock Manager",
    "Stock User",
    "Item Manager",
    "Sales Manager",
    "Sales User",
    "Sales Master Manager",  # territories, customer groups
    "Purchase Manager",
    "Purchase User",
    "Purchase Master Manager",  # supplier groups
]
ENV_PATH = Path(".env")


def set_env_values(path: Path, values: dict[str, str]) -> None:
    """Replace or append KEY=value lines in an env file, keeping every other line as it is.

    Writes to a temporary file first and renames it, so a crash can't leave a half-written .env.
    """
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(values)
    for i, line in enumerate(lines):
        match = re.match(r"^([A-Z][A-Z0-9_]*)=", line)
        if match and match.group(1) in remaining:
            key = match.group(1)
            lines[i] = f"{key}={remaining.pop(key)}"
    lines.extend(f"{key}={value}" for key, value in remaining.items())
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".env.")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    if path.exists():
        os.chmod(tmp, path.stat().st_mode & 0o777)
    os.replace(tmp, path)


def key_works(settings: Settings, transport: httpx.BaseTransport | None = None) -> bool:
    """True if .env's API key signs in as API_USER."""
    if not (settings.erpnext_api_key and settings.erpnext_api_secret):
        return False
    client = ErpClient(
        settings.erpnext_url,
        settings.erpnext_api_key.get_secret_value(),
        settings.erpnext_api_secret.get_secret_value(),
        retries=1,
        transport=transport,
    )
    with client:
        try:
            return client.logged_user() == API_USER
        except ErpError:
            return False


def admin_session(settings: Settings, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """Return an HTTP client signed in as Administrator (session cookie, as in the Frappe docs)."""
    if settings.erpnext_admin_password is None:
        raise SystemExit("ERPNEXT_ADMIN_PASSWORD is blank in .env. Run `make env-secrets`.")
    http = httpx.Client(base_url=settings.erpnext_url, timeout=60, transport=transport)
    login = http.post(
        "/api/method/login",
        json={"usr": "Administrator", "pwd": settings.erpnext_admin_password.get_secret_value()},
    )
    if login.is_error:
        http.close()
        raise SystemExit(
            f"Administrator login failed (HTTP {login.status_code}). "
            "Check that ERPNext is up (`make erp-ps`) and that `make erp-up` set the password."
        )
    return http


def ensure_user(http: httpx.Client) -> list[str]:
    """Create API_USER if missing and give it any missing roles. Returns the roles it added."""
    found = http.get(f"/api/resource/User/{API_USER}")
    if found.status_code == 404:
        created = http.post(
            "/api/resource/User",
            json={
                "email": API_USER,
                "first_name": "Bluefield",
                "last_name": "Integration (demo)",
                "user_type": "System User",
                "send_welcome_email": 0,
                "roles": [{"role": role} for role in API_USER_ROLES],
            },
        )
        if created.is_error:
            raise SystemExit(f"Could not create {API_USER} (HTTP {created.status_code}).")
        return list(API_USER_ROLES)
    if found.is_error:
        raise SystemExit(f"Could not read {API_USER} (HTTP {found.status_code}).")
    current = [row["role"] for row in found.json()["data"].get("roles", [])]
    missing = [role for role in API_USER_ROLES if role not in current]
    if missing:
        # PUT replaces the whole roles table, so send the current roles plus the missing ones.
        updated = http.put(
            f"/api/resource/User/{API_USER}",
            json={"roles": [{"role": role} for role in current + missing]},
        )
        if updated.is_error:
            raise SystemExit(f"Could not add roles to {API_USER} (HTTP {updated.status_code}).")
    return missing


def create_key(http: httpx.Client) -> dict[str, str]:
    """Generate a new API secret for API_USER (this replaces any previous secret)."""
    keys = http.post(
        "/api/method/frappe.core.doctype.user.user.generate_keys", json={"user": API_USER}
    )
    if keys.is_error:
        raise SystemExit(f"Could not generate an API key (HTTP {keys.status_code}).")
    message = keys.json()["message"]
    return {"ERPNEXT_API_KEY": message["api_key"], "ERPNEXT_API_SECRET": message["api_secret"]}


def main() -> int:
    settings = Settings()
    log = get_logger("erp.api_user", new_run_id(), settings.log_level)
    http = admin_session(
        settings
    )  # already used to log in, so close it with try/finally, not `with`
    try:
        added = ensure_user(http)
        if added:
            log.info("Roles added", extra={"user": API_USER, "roles": added})
        if key_works(settings):
            log.info("API key in .env already works; kept", extra={"user": API_USER})
            return 0
        set_env_values(ENV_PATH, create_key(http))
    finally:
        http.close()
    if not key_works(Settings()):
        log.error("New API key was written to .env but does not work", extra={"user": API_USER})
        return 1
    log.info("API key created and written to .env", extra={"user": API_USER})
    return 0


if __name__ == "__main__":
    sys.exit(main())
