"""Static checks on the dbt project and the pipeline runner. No database needed; runs in CI."""

import re

import pytest
import yaml

from pipeline import run
from shared.config import Settings
from tests.helpers import ROOT

DBT = ROOT / "pipeline" / "dbt"
STAGING = sorted((DBT / "models" / "staging").glob("stg_*.sql"))
MARTS = sorted((DBT / "models" / "marts").glob("*.sql"))


def load_yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_marts_are_tables_readable_only_by_reporting_reader():
    models = load_yaml(DBT / "dbt_project.yml")["models"]["bluefield"]
    assert models["marts"]["+materialized"] == "table"
    assert models["marts"]["+grants"] == {"select": ["reporting_reader"]}
    assert "+grants" not in models["staging"], "staging must stay private"


def test_schema_names_are_used_as_written():
    macro = (DBT / "macros" / "generate_schema_name.sql").read_text(encoding="utf-8")
    assert "custom_schema_name | trim" in macro
    assert "target.schema }}_" not in macro


def test_profile_holds_no_secrets():
    profile = (DBT / "profiles.yml").read_text(encoding="utf-8")
    assert "env_var('BLUEFIELD_PG_PASSWORD')" in profile
    assert not re.search(r"password:\s*[^\"{\s]", profile)


@pytest.mark.parametrize(
    "path",
    [
        p
        for p in STAGING
        if p.stem not in {"stg_customers", "stg_suppliers", "stg_items", "stg_stock_levels"}
    ],
    ids=lambda p: p.stem,
)
def test_transaction_models_keep_only_submitted_documents(path):
    assert "docstatus = 1" in path.read_text(encoding="utf-8")


def test_every_model_is_documented_as_demo_data():
    documented = {}
    for yml in (DBT / "models").rglob("_*.yml"):
        for model in load_yaml(yml).get("models", []):
            documented[model["name"]] = model.get("description", "")
    for path in STAGING + MARTS:
        assert "Demo data only." in documented.get(path.stem, ""), path.stem


def test_every_mart_says_where_its_numbers_come_from():
    for path in MARTS:
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
        assert first_line.startswith("--") and "Demo data only." in first_line, path.name


def test_dbt_env_uses_settings_and_hides_nothing_in_code():
    settings = Settings(_env_file=None, postgres_password="pw-from-env", postgres_port=6543)
    env = run.dbt_env(settings, "run123")
    assert env["BLUEFIELD_PG_PASSWORD"] == "pw-from-env"
    assert env["BLUEFIELD_PG_PORT"] == "6543"
    assert env["BLUEFIELD_RUN_ID"] == "run123"


def test_dbt_project_parses(monkeypatch, tmp_path):
    """Compile-time check of every model, test and ref (dbt parse does not connect)."""
    from dbt.cli.main import dbtRunner

    for key, value in {
        "BLUEFIELD_PG_HOST": "localhost",
        "BLUEFIELD_PG_PORT": "5432",
        "BLUEFIELD_PG_DB": "bluefield",
        "BLUEFIELD_PG_USER": "parse_only",
        "BLUEFIELD_PG_PASSWORD": "parse_only",
    }.items():
        monkeypatch.setenv(key, value)
    result = dbtRunner().invoke(
        [
            "parse",
            "--project-dir",
            str(DBT),
            "--profiles-dir",
            str(DBT),
            "--target-path",
            str(tmp_path / "target"),
            "--log-path",
            str(tmp_path / "logs"),
            "--quiet",
        ]  # fmt: skip
    )
    assert result.success, result.exception
    nodes = result.result.nodes
    assert {n.name for n in nodes.values() if n.resource_type == "model"} >= {p.stem for p in MARTS}
