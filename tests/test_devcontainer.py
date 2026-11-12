"""Static checks for the Codespaces dev container. No Docker needed; runs in CI."""

import json
import re

import pytest

from tests.helpers import ROOT, env_example_values

DEVCONTAINER_PATH = ROOT / ".devcontainer" / "devcontainer.json"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

IMAGE_PATTERN = r"mcr\.microsoft\.com/devcontainers/python:\d+\.\d+\.\d+-(.+)-bookworm"
DOCKER_IN_DOCKER = "ghcr.io/devcontainers/features/docker-in-docker:"
CI_UV_PATTERN = r'setup-uv@\S+\s+with:\s+version:\s*"([^"]+)"'

# Web UIs that should show up, labelled, in the Codespaces Ports tab.
UI_PORTS = {
    "METABASE_PORT": "Metabase",
    "N8N_PORT": "n8n",
    "MAILPIT_UI_PORT": "Mailpit",
    "ERPNEXT_PORT": "ERPNext",
}
# Raw protocol ports that nobody needs in a browser.
NON_UI_PORTS = ("POSTGRES_PORT", "MAILPIT_SMTP_PORT")


@pytest.fixture(scope="module")
def devcontainer() -> dict:
    return json.loads(DEVCONTAINER_PATH.read_text(encoding="utf-8"))


def test_image_is_pinned_and_matches_python_version(devcontainer):
    python_version = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    image = devcontainer["image"]
    match = re.fullmatch(IMAGE_PATTERN, image)
    assert match, f"image {image!r} must use an exact devcontainer image version"
    assert match.group(1) == python_version


def test_features_are_pinned_and_include_docker(devcontainer):
    features = devcontainer["features"]
    for ref in features:
        assert re.search(r":\d+\.\d+\.\d+$", ref), f"feature {ref!r} is not pinned exactly"
    # Docker-in-docker runs the daemon inside the container, so 127.0.0.1 port bindings
    # stay reachable for VS Code port forwarding.
    assert any(ref.startswith(DOCKER_IN_DOCKER) for ref in features)


def test_uv_version_matches_ci(devcontainer):
    container_uv = re.search(r"uv==(\S+)", devcontainer["postCreateCommand"])
    ci_uv = re.search(CI_UV_PATTERN, CI_WORKFLOW.read_text(encoding="utf-8"))
    assert container_uv and ci_uv, "uv must be pinned in both the dev container and CI"
    assert container_uv.group(1) == ci_uv.group(1)


def test_ui_ports_are_forwarded_and_labelled(devcontainer):
    env = env_example_values()
    expected = {int(env[key]): label for key, label in UI_PORTS.items()}
    assert set(devcontainer["forwardPorts"]) == set(expected)
    attrs = devcontainer["portsAttributes"]
    for port, label in expected.items():
        assert attrs[str(port)]["label"] == label
        assert attrs[str(port)]["onAutoForward"] == "silent"


def test_database_and_smtp_ports_are_not_auto_forwarded(devcontainer):
    env = env_example_values()
    for key in NON_UI_PORTS:
        port = env[key]
        assert int(port) not in devcontainer["forwardPorts"]
        assert devcontainer["portsAttributes"][port]["onAutoForward"] == "ignore"


def test_ports_stay_private(devcontainer):
    # Private is the Codespaces default. Never make a port public in config.
    for attrs in devcontainer["portsAttributes"].values():
        assert attrs.get("visibility", "private") == "private"
