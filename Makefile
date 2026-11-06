# Bluefield Supply Co. portfolio: common commands.
# Runs in GitHub Codespaces or any Linux/macOS shell with GNU make.

COMPOSE_FILE := infra/docker-compose.yml
COMPOSE := docker compose -f $(COMPOSE_FILE) --env-file .env
SECRET_KEYS := POSTGRES_PASSWORD METABASE_DB_PASSWORD N8N_DB_PASSWORD MB_ENCRYPTION_SECRET_KEY N8N_ENCRYPTION_KEY

.DEFAULT_GOAL := help
.PHONY: help setup lint format test test-all up down logs ps check-stack db-init env-secrets check-compose

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-12s %s\n", $$1, $$2}'

setup: ## Install Python 3.12 and all dependencies with uv
	@uv python install 3.12
	@uv sync --locked
	@test -f .env || { cp .env.example .env; echo "Created .env from .env.example. Fill in your own values."; }

lint: ## Run ruff lint and format checks
	@uv run ruff check .
	@uv run ruff format --check .

format: ## Auto-fix lint issues and format code
	@uv run ruff check --fix .
	@uv run ruff format .

test: ## Run unit tests (skips integration tests)
	@uv run pytest -m "not integration"

test-all: ## Run all tests, including integration tests that need live services
	@uv run pytest

check-compose:
	@test -f $(COMPOSE_FILE) || { echo "$(COMPOSE_FILE) not created yet (Foundation Step 5)."; exit 1; }
	@test -f .env || { echo ".env missing. Run 'make setup' first."; exit 1; }

env-secrets: ## Fill blank stack secrets in .env with random values (never overwrites, never prints)
	@test -f .env || { cp .env.example .env; echo "Created .env from .env.example."; }
	@if [ -n "$$(tail -c1 .env)" ]; then echo >> .env; fi
	@for k in $(SECRET_KEYS); do \
		v=$$(openssl rand -hex 32); \
		if grep -q "^$$k=." .env; then echo "$$k: already set, kept"; \
		elif grep -q "^$$k=$$" .env; then sed -i "s|^$$k=$$|$$k=$$v|" .env; echo "$$k: generated"; \
		else echo "$$k=$$v" >> .env; echo "$$k: generated"; fi; \
	done

up: check-compose ## Start the Docker stack and wait until every service is healthy
	@$(COMPOSE) up -d --wait --wait-timeout 420

down: check-compose ## Stop the Docker stack (keeps data volumes)
	@$(COMPOSE) down

logs: check-compose ## Follow logs from the Docker stack
	@$(COMPOSE) logs -f

ps: check-compose ## Show each service and its health status
	@$(COMPOSE) ps

check-stack: ## Run the live checks against the running stack
	@uv run pytest -m integration tests/integration -v

db-init: check-compose ## Rerun the Postgres init script (safe to repeat)
	@$(COMPOSE) exec postgres bash /docker-entrypoint-initdb.d/10-bluefield.sh
