"""Live checks for the shared Docker stack (Foundation Step 5).

Start the stack first with `make up`, then run `make check-stack`.
Connection details come from .env. Passwords are never printed.
"""

import json
import smtplib
import time
import urllib.request
import uuid
from email.message import EmailMessage

import psycopg
import pytest
from pydantic import SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

pytestmark = pytest.mark.integration

HOST = "127.0.0.1"
REPORTING_SCHEMAS = {"raw", "staging", "marts", "ops"}


class StackSettings(BaseSettings):
    """Values the checks need from .env, with the same defaults as the compose file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "bluefield_admin"
    postgres_db: str = "bluefield"
    postgres_password: SecretStr
    metabase_db_password: SecretStr
    metabase_port: int = 3000
    n8n_port: int = 5678
    mailpit_ui_port: int = 8025
    mailpit_smtp_port: int = 1025


@pytest.fixture(scope="module")
def stack() -> StackSettings:
    try:
        return StackSettings()
    except ValidationError as exc:
        missing = sorted(str(err["loc"][0]).upper() for err in exc.errors())
    pytest.fail(f"Missing from .env: {missing}. Run `make env-secrets`, then `make up`.")


def connect(stack: StackSettings, user: str, password: SecretStr, dbname: str):
    return psycopg.connect(
        host=stack.postgres_host,
        port=stack.postgres_port,
        user=user,
        password=password.get_secret_value(),
        dbname=dbname,
        connect_timeout=5,
    )


def http_get(url: str) -> tuple[int, bytes]:
    with urllib.request.urlopen(url, timeout=10) as resp:
        return resp.status, resp.read()


def test_postgres_has_reporting_schemas(stack):
    with connect(stack, stack.postgres_user, stack.postgres_password, stack.postgres_db) as conn:
        rows = conn.execute(
            "SELECT nspname FROM pg_namespace WHERE nspname = ANY(%s)",
            (list(REPORTING_SCHEMAS),),
        ).fetchall()
    assert {r[0] for r in rows} == REPORTING_SCHEMAS


def test_postgres_has_app_databases(stack):
    with connect(stack, stack.postgres_user, stack.postgres_password, stack.postgres_db) as conn:
        rows = conn.execute(
            "SELECT datname, pg_get_userbyid(datdba) FROM pg_database "
            "WHERE datname IN ('metabase', 'n8n')"
        ).fetchall()
    assert dict(rows) == {"metabase": "metabase", "n8n": "n8n"}


def test_metabase_role_can_use_only_its_own_database(stack):
    with connect(stack, "metabase", stack.metabase_db_password, "metabase") as conn:
        assert conn.execute("SELECT current_user").fetchone()[0] == "metabase"
    with pytest.raises(psycopg.OperationalError, match="permission denied"):
        connect(stack, "metabase", stack.metabase_db_password, stack.postgres_db)


def test_metabase_is_healthy(stack):
    status, body = http_get(f"http://{HOST}:{stack.metabase_port}/api/health")
    assert status == 200
    assert json.loads(body) == {"status": "ok"}


def test_n8n_is_ready(stack):
    # Readiness is 200 only after n8n has connected to Postgres and run migrations.
    status, _ = http_get(f"http://{HOST}:{stack.n8n_port}/healthz/readiness")
    assert status == 200


def test_mailpit_receives_email(stack):
    subject = f"Bluefield stack check {uuid.uuid4().hex[:8]} (demo)"
    msg = EmailMessage()
    msg["From"] = "stack-check@bluefield.example"
    msg["To"] = "it@bluefield.example"
    msg["Subject"] = subject
    msg.set_content("Demo message from tests/integration/test_stack.py.")

    with smtplib.SMTP(HOST, stack.mailpit_smtp_port, timeout=10) as smtp:
        smtp.send_message(msg)

    deadline = time.monotonic() + 10
    subjects: list[str] = []
    while time.monotonic() < deadline:
        _, body = http_get(f"http://{HOST}:{stack.mailpit_ui_port}/api/v1/messages?limit=50")
        subjects = [m["Subject"] for m in json.loads(body)["messages"]]
        if subject in subjects:
            return
        time.sleep(0.5)
    pytest.fail(f"Mailpit never showed the test email. Latest subjects: {subjects[:5]}")
