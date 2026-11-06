"""Live checks for ERPNext (Foundation Step 5).

Start ERPNext first with `make erp-up`, then run `make erp-check`.
Connection details come from .env. Passwords are never printed.
"""

import json
import urllib.error
import urllib.parse
import urllib.request

import pytest
from pydantic import SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

pytestmark = pytest.mark.integration

ADMIN_USER = "Administrator"
PWD_YML_DEFAULT_PASSWORD = "admin"  # Public default from frappe_docker's pwd.yml, not a secret.


class ErpSettings(BaseSettings):
    """Values the checks need from .env, with the same defaults as .env.example."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    erpnext_port: int = 8080
    erpnext_admin_password: SecretStr


@pytest.fixture(scope="module")
def erp() -> ErpSettings:
    try:
        return ErpSettings()
    except ValidationError as exc:
        missing = sorted(str(err["loc"][0]).upper() for err in exc.errors())
    pytest.fail(f"Missing from .env: {missing}. Run `make env-secrets`, then `make erp-up`.")


def base_url(erp: ErpSettings) -> str:
    return f"http://127.0.0.1:{erp.erpnext_port}"


def login_status(erp: ErpSettings, password: str) -> int:
    body = urllib.parse.urlencode({"usr": ADMIN_USER, "pwd": password}).encode()
    request = urllib.request.Request(f"{base_url(erp)}/api/method/login", data=body)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_ping_answers_pong(erp):
    with urllib.request.urlopen(f"{base_url(erp)}/api/method/ping", timeout=10) as response:
        assert json.load(response) == {"message": "pong"}


# Keep the successful login first: it resets Frappe's failed-login counter for Administrator.
def test_admin_login_uses_password_from_env(erp):
    assert login_status(erp, erp.erpnext_admin_password.get_secret_value()) == 200


def test_default_admin_password_is_rejected(erp):
    assert login_status(erp, PWD_YML_DEFAULT_PASSWORD) == 401
