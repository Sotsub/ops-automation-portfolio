# Bluefield Supply Co. portfolio: common commands.
# Runs in GitHub Codespaces or any Linux/macOS shell with GNU make.

COMPOSE_FILE := infra/docker-compose.yml
COMPOSE := docker compose -f $(COMPOSE_FILE) --env-file .env

.DEFAULT_GOAL := help
.PHONY: help setup lint format test test-all up down logs check-compose

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

up: check-compose ## Start the Docker stack
	@$(COMPOSE) up -d

down: check-compose ## Stop the Docker stack
	@$(COMPOSE) down

logs: check-compose ## Follow logs from the Docker stack
	@$(COMPOSE) logs -f
