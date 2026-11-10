"""Small readers shared by the static tests (no Docker or live services needed)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = ROOT / ".env.example"
MAKEFILE = ROOT / "Makefile"


def env_example_values() -> dict[str, str]:
    """Return KEY=value pairs from .env.example, ignoring comments and blank lines."""
    values = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def make_variable(name: str) -> str:
    """Return the right-hand side of a simple Makefile variable assignment."""
    text = MAKEFILE.read_text(encoding="utf-8")
    match = re.search(rf"^{name}\s*[:?]?=\s*(.+)$", text, re.MULTILINE)
    assert match, f"Makefile does not define {name}"
    return match.group(1).strip()


def make_targets() -> set[str]:
    """Return every target name defined at the start of a Makefile line."""
    text = MAKEFILE.read_text(encoding="utf-8")
    return set(re.findall(r"^([a-zA-Z][a-zA-Z0-9_-]*):(?!=)", text, re.MULTILINE))
