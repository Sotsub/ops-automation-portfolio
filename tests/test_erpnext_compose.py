"""Static checks for how ERPNext is started (Foundation Step 5). No Docker needed; runs in CI.

ERPNext runs from the official frappe_docker pwd.yml (cloned outside this repo) plus
infra/erpnext/compose.override.yml. These tests check the parts this repo controls.
"""

import re

import pytest
import yaml

from tests.helpers import ROOT, env_example_values, make_rule, make_variable

OVERRIDE_PATH = ROOT / "infra" / "erpnext" / "compose.override.yml"
STACK_COMPOSE_PATH = ROOT / "infra" / "docker-compose.yml"

PORT_VAR = re.compile(r"\$\{([A-Z][A-Z0-9_]*):-(\d+)\}")


class _ComposeLoader(yaml.SafeLoader):
    """SafeLoader that understands Compose's !override and !reset merge tags."""


def _tagged_sequence(loader, node):
    return {"tag": node.tag, "value": loader.construct_sequence(node)}


for _tag in ("!override", "!reset"):
    _ComposeLoader.add_constructor(_tag, _tagged_sequence)


@pytest.fixture(scope="module")
def frontend_ports() -> dict:
    override = yaml.load(OVERRIDE_PATH.read_text(encoding="utf-8"), Loader=_ComposeLoader)
    assert set(override["services"]) == {"frontend"}, "override should only touch frontend"
    return override["services"]["frontend"]["ports"]


def test_override_replaces_pwd_yml_ports(frontend_ports):
    # Without !override, Compose would append to pwd.yml's "8080:8080" (all interfaces).
    assert frontend_ports["tag"] == "!override"


def test_erpnext_binds_to_localhost_only(frontend_ports):
    assert frontend_ports["value"], "frontend must publish a port"
    for port in frontend_ports["value"]:
        assert port.startswith("127.0.0.1:"), f"port {port!r} is not localhost-only"
        assert port.endswith(":8080"), "nginx inside the frontend container listens on 8080"


def test_erpnext_port_does_not_clash_with_shared_stack(frontend_ports):
    erp_vars = dict(PORT_VAR.findall(" ".join(frontend_ports["value"])))
    assert erp_vars == {"ERPNEXT_PORT": "8080"}
    stack_ports = set(PORT_VAR.findall(STACK_COMPOSE_PATH.read_text(encoding="utf-8")))
    env = env_example_values()
    stack_defaults = {default for _, default in stack_ports}
    stack_configured = {env[name] for name, _ in stack_ports if env.get(name)}
    erp_port = env["ERPNEXT_PORT"]
    assert erp_port not in stack_defaults | stack_configured, f"port {erp_port} already in use"


def test_env_example_has_erpnext_keys():
    env = env_example_values()
    assert env["ERPNEXT_PORT"] == "8080"
    assert env["ERPNEXT_URL"] == f"http://localhost:{env['ERPNEXT_PORT']}"
    assert env["ERPNEXT_ADMIN_PASSWORD"] == "", "never put a real password in .env.example"


def test_env_secrets_generates_the_admin_password():
    assert "ERPNEXT_ADMIN_PASSWORD" in make_variable("SECRET_KEYS").split()


def test_frappe_docker_is_pinned_to_a_full_commit():
    assert re.fullmatch(r"[0-9a-f]{40}", make_variable("FRAPPE_DOCKER_REF"))


def test_frappe_docker_clone_lives_outside_the_repo():
    clone_dir = make_variable("FRAPPE_DOCKER_DIR")
    assert clone_dir.startswith("$(CURDIR)/../"), "the clone must sit outside this repository"


def test_erpnext_uses_its_own_compose_project():
    erp_compose = make_variable("ERP_COMPOSE")
    assert "-p $(ERP_PROJECT)" in erp_compose
    assert make_variable("ERP_PROJECT") == "bluefield-erp"
    assert '-f "$(FRAPPE_DOCKER_DIR)/pwd.yml" -f infra/erpnext/compose.override.yml' in erp_compose
    stack_name = yaml.safe_load(STACK_COMPOSE_PATH.read_text(encoding="utf-8"))["name"]
    assert stack_name != "bluefield-erp"


def test_erp_pull_downloads_each_image_once():
    # pwd.yml reuses one image across 8 services; pulling per service filled the Codespace disk.
    prereqs, recipe = make_rule("erp-pull")
    assert {"erp-clone", "erp-preflight"} <= set(prereqs)
    assert "config --images | sort -u" in recipe
    assert "docker image inspect" in recipe, "images already present must be skipped on rerun"


def test_erp_up_pulls_first_and_never_lets_compose_pull():
    prereqs, recipe = make_rule("erp-up")
    assert "erp-pull" in prereqs
    assert "up -d --pull never" in recipe
