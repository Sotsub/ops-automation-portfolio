# ops-automation-portfolio

A workflow automation portfolio built around **Bluefield Supply Co., a fictional wholesale distributor**.
It connects an ERP (ERPNext), a reporting database (Postgres), BI dashboards (Metabase), workflow
automation (n8n), and AI tools, and controls what the AI is allowed to do.

> **Demo data only.** Every company, customer, and number in this repository is fictional.

## Status

| Part | Folder | Status |
| --- | --- | --- |
| Foundation | `infra/`, `erp/`, `shared/` | Repository scaffolded |
| 1. ERP-to-dashboard pipeline | `pipeline/` | Not started |
| 2. AI reporting assistant | `assistant/` | Not started |
| 3. Multi-system sync | `sync/` | Not started |
| 4. Automated department reports | `reports/` | Not started |
| 5. AI tool evaluation | `eval/` | Not started |
| 6. Data investigation agent | `agent/` | Not started |

## Repository layout

```
infra/      Docker Compose and environment templates
erp/        ERPNext seed and setup scripts
pipeline/   Project 1
assistant/  Project 2
sync/       Project 3
reports/    Project 4
eval/       Project 5
agent/      Project 6
shared/     Config, JSON logging, database helpers
docs/       Architecture, decisions, runbooks, evidence
tests/      Test suite
```

## Setup

Requirements: [uv](https://docs.astral.sh/uv/) and Git. uv installs Python 3.12 itself.
Docker is needed only from Foundation Step 5 onward.

### GitHub Codespaces, Linux, or macOS

```bash
make setup   # installs Python 3.12 and dependencies, creates .env from .env.example
make lint
make test
```

Run `make help` to see every target. `make up`, `make down`, and `make logs` work once
`infra/docker-compose.yml` exists (Foundation Step 5).

### Windows without make

```powershell
uv python install 3.12
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pytest -m "not integration"
```

## Configuration and secrets

All settings come from environment variables, loaded by `shared/config.py`. Copy `.env.example` to
`.env` and fill in your own values. `.env` is gitignored and must never be committed.

| Variable | Needed from | Purpose |
| --- | --- | --- |
| `APP_ENV` | Now | `dev`, `test`, or `demo` |
| `LOG_LEVEL` | Now | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `AI_PROVIDER` | Project 2 | AI provider name |
| `AI_MODEL` | Project 2 | Exact model name. Never hardcoded |
| `AI_API_KEY` | Project 2 | API key. Stored as a secret and masked in logs |

## Tests

- `make test`: unit tests, which need no running services. CI runs these on every push.
- `make test-all`: also runs tests marked `@pytest.mark.integration`, which need live services.

## Engineering conventions

- Structured JSON logs with a `run_id` (`shared/logging.py`).
- No secrets or AI model names in code.
- Lint (ruff) and unit tests run in GitHub Actions on every push and pull request.
