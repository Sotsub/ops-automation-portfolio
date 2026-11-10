"""Static checks for the shared Docker stack. No Docker needed, so these run in CI."""

import re

import pytest
import yaml

from tests.helpers import ROOT, env_example_values, make_targets, make_variable

COMPOSE_PATH = ROOT / "infra" / "docker-compose.yml"
INIT_SCRIPT = ROOT / "infra" / "postgres" / "init" / "10-bluefield.sh"

EXPECTED_SERVICES = {"postgres", "metabase", "n8n", "mailpit"}
# None = no profile, so the service is part of the always-on core stack.
EXPECTED_PROFILES = {
    "postgres": None,
    "mailpit": None,
    "metabase": ["reporting"],
    "n8n": ["automation"],
}
REPORTING_SCHEMAS = ["raw", "staging", "marts", "ops"]

# ${VAR}, ${VAR:-default}, ${VAR:?error}, but not the escaped $${VAR} used inside containers.
COMPOSE_VAR = re.compile(r"(?<!\$)\$\{([A-Z][A-Z0-9_]*)")
SECRET_NAME = re.compile(r"(PASS|PASSWORD|SECRET|_KEY)$|SECRET")
REQUIRED_VAR = re.compile(r"^\$\{[A-Z][A-Z0-9_]*:\?[^}]+\}$")
PINNED_TAG = re.compile(r":v?\d+\.\d+(\.\d+)*(-[a-z0-9.]+)?$")


@pytest.fixture(scope="module")
def compose_text() -> str:
    return COMPOSE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def compose(compose_text) -> dict:
    return yaml.safe_load(compose_text)


@pytest.fixture(scope="module")
def services(compose) -> dict:
    return compose["services"]


def test_expected_services_only(services):
    assert set(services) == EXPECTED_SERVICES


def test_services_are_in_the_expected_profiles(services):
    for name, expected in EXPECTED_PROFILES.items():
        assert services[name].get("profiles") == expected, f"{name}: wrong profiles"


def test_profiled_services_depend_only_on_core(services):
    # Compose does not start a dependency that sits behind a disabled profile.
    for name, svc in services.items():
        for dependency in svc.get("depends_on") or {}:
            assert not services[dependency].get("profiles"), (
                f"{name} depends on {dependency}, which must stay in the core (unprofiled) stack"
            )


def test_every_profile_has_make_targets_and_service_list(services):
    targets = make_targets()
    profiles = {p for svc in services.values() for p in svc.get("profiles") or []}
    for profile in profiles:
        assert {f"up-{profile}", f"stop-{profile}"} <= targets, f"missing make targets: {profile}"
        in_profile = {n for n, s in services.items() if profile in (s.get("profiles") or [])}
        listed = set(make_variable(f"{profile.upper()}_SERVICES").split())
        assert listed == in_profile, f"{profile.upper()}_SERVICES is out of date"
    all_profiles = make_variable("ALL_PROFILES").split()
    assert set(all_profiles[1::2]) == profiles, "ALL_PROFILES must name every profile"
    assert set(all_profiles[::2]) == {"--profile"}


def test_images_are_pinned_to_exact_versions(services):
    for name, svc in services.items():
        image = svc["image"]
        assert PINNED_TAG.search(image), f"{name}: image {image!r} is not pinned to a version"
        assert not image.endswith((":latest", ":stable")), f"{name}: floating tag {image!r}"


def test_every_service_has_a_healthcheck(services):
    for name, svc in services.items():
        assert svc.get("healthcheck", {}).get("test"), f"{name}: missing healthcheck"


def test_ports_bind_to_localhost_only(services):
    for name, svc in services.items():
        for port in svc.get("ports", []):
            assert isinstance(port, str), f"{name}: use the 'ip:host:container' string form"
            assert port.startswith("127.0.0.1:"), f"{name}: port {port!r} is not localhost-only"


def test_data_uses_named_volumes(compose, services):
    declared = set(compose.get("volumes") or {})
    for name, svc in services.items():
        for mount in svc.get("volumes", []):
            source = mount.split(":", 1)[0]
            if source.startswith("."):
                assert mount.endswith(":ro"), f"{name}: bind mount {mount!r} must be read-only"
            else:
                assert source in declared, f"{name}: volume {source!r} is not declared"


def test_postgres_volume_matches_postgres_18_layout(services):
    # Postgres 18+ images store data under /var/lib/postgresql/<major>/docker.
    mounts = services["postgres"]["volumes"]
    assert "postgres-data:/var/lib/postgresql" in mounts


def test_secrets_come_from_env_and_are_required(services):
    for name, svc in services.items():
        for key, value in (svc.get("environment") or {}).items():
            if SECRET_NAME.search(key):
                assert REQUIRED_VAR.match(str(value)), (
                    f"{name}: {key} must be a required ${{VAR:?message}} reference"
                )


def test_apps_wait_for_healthy_postgres(services):
    for name in ("metabase", "n8n"):
        condition = services[name]["depends_on"]["postgres"]["condition"]
        assert condition == "service_healthy", name


def test_env_example_lists_every_compose_variable(compose_text):
    used = set(COMPOSE_VAR.findall(compose_text))
    missing = used - set(env_example_values())
    assert not missing, f".env.example is missing: {sorted(missing)}"


def test_env_example_leaves_secrets_blank():
    for key, value in env_example_values().items():
        if SECRET_NAME.search(key):
            assert value == "", f".env.example must not contain a value for {key}"


def test_init_script_creates_reporting_schemas_idempotently():
    sql = INIT_SCRIPT.read_text(encoding="utf-8")
    for schema in REPORTING_SCHEMAS:
        assert f"CREATE SCHEMA IF NOT EXISTS {schema};" in sql


def test_init_script_has_no_inline_passwords():
    sql = INIT_SCRIPT.read_text(encoding="utf-8")
    # Passwords must arrive as psql variables, never as literal strings.
    assert not re.search(r"PASSWORD\s+'", sql, re.IGNORECASE)
    assert "PASSWORD :'metabase_pw'" in sql
    assert "PASSWORD :'n8n_pw'" in sql
