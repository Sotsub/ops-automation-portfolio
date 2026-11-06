# Project rules

This is a portfolio system for Bluefield Supply Co., a fictional distributor.
It demonstrates ERP integration, SQL reporting, workflow automation, and safe AI use.

## Engineering rules
- Make one milestone change at a time. Plan before editing.
- Write or update tests with every behavior change.
- Run lint and tests before calling work complete.
- Use structured JSON logs with a run_id.
- Use environment variables for secrets and model names. Never read or print .env values.
- Make jobs safe to rerun.
- Check current official docs before relying on a vendor API detail.

## Data and AI rules
- SQL calculates every reported number. AI explains results but never invents them.
- AI gets read-only access through approved views.
- AI may not change business data without a human approval step.
- Clearly label all demo data and results.

## Done means
- Acceptance checks pass.
- README and runbook are updated.
- Evidence is saved in docs/evidence/.

## Repository facts
- Python 3.12, managed with uv. One `pyproject.toml` and `uv.lock` for the whole repo.
- Commands in Codespaces or Linux: `make setup`, `make lint`, `make test`.
- Commands on Windows (no make): `uv sync --locked`, `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run pytest -m "not integration"`.
- Settings: `shared/config.py` (pydantic-settings). Logging: `shared/logging.py`
  (`get_logger(name, run_id)`, `new_run_id()`).
- Mark tests that need live services with `@pytest.mark.integration`. CI skips them.
- Keep the stack free: no paid services, and only fictional data with free AI tiers.
- `docs/Build_Guide.md` is private and gitignored. Never commit it, and never copy its
  contents into committed files.
- Commit or push only when asked.
