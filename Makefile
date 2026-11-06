# Bluefield Supply Co. portfolio: common commands.
# Runs in GitHub Codespaces or any Linux/macOS shell with GNU make.

COMPOSE_FILE := infra/docker-compose.yml
COMPOSE := docker compose -f $(COMPOSE_FILE) --env-file .env
SECRET_KEYS := POSTGRES_PASSWORD METABASE_DB_PASSWORD N8N_DB_PASSWORD MB_ENCRYPTION_SECRET_KEY N8N_ENCRYPTION_KEY ERPNEXT_ADMIN_PASSWORD

# ERPNext runs from the official frappe_docker pwd.yml. The clone lives OUTSIDE this repository
# (next to it by default), so it can never be committed here.
FRAPPE_DOCKER_DIR ?= $(CURDIR)/../frappe_docker
# frappe_docker main on 2026-11-06. Its pwd.yml pins frappe/erpnext:v16.54.0. Change deliberately.
FRAPPE_DOCKER_REF := 46c7ced81efbd4a119e14b81bf78e3b77cad3309
ERP_PROJECT := bluefield-erp
ERP_COMPOSE := docker compose -p $(ERP_PROJECT) -f "$(FRAPPE_DOCKER_DIR)/pwd.yml" -f infra/erpnext/compose.override.yml --env-file .env
ERP_MIN_COMPOSE := 2.24.4
# Shell snippet that reads one key from .env without sourcing the file or printing the value.
env_value = $$(sed -n 's/^$(1)=//p' .env | tail -n 1 | tr -d '\r')

.DEFAULT_GOAL := help
.PHONY: help setup lint format test test-all up down logs ps check-stack db-init env-secrets check-compose \
	erp-clone erp-preflight erp-up erp-down erp-logs erp-ps erp-check

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
	@uv run pytest -m integration tests/integration/test_stack.py -v

db-init: check-compose ## Rerun the Postgres init script (safe to repeat)
	@$(COMPOSE) exec postgres bash /docker-entrypoint-initdb.d/10-bluefield.sh

# --- ERPNext (Foundation Step 5) ---------------------------------------------------------------

erp-clone: ## Clone frappe_docker outside this repo at the pinned commit (safe to rerun)
	@target=$$(realpath -m "$(FRAPPE_DOCKER_DIR)"); repo=$$(realpath -m "$(CURDIR)"); \
	case "$$target/" in "$$repo/"*) \
		echo "FRAPPE_DOCKER_DIR must be outside this repository (got $$target)."; exit 1;; esac
	@if [ ! -d "$(FRAPPE_DOCKER_DIR)/.git" ]; then \
		echo "Cloning frappe_docker into $(FRAPPE_DOCKER_DIR)"; \
		git clone --quiet https://github.com/frappe/frappe_docker "$(FRAPPE_DOCKER_DIR)"; \
	fi
	@git -C "$(FRAPPE_DOCKER_DIR)" cat-file -e "$(FRAPPE_DOCKER_REF)^{commit}" 2>/dev/null \
		|| git -C "$(FRAPPE_DOCKER_DIR)" fetch --quiet origin
	@git -C "$(FRAPPE_DOCKER_DIR)" -c advice.detachedHead=false checkout --quiet "$(FRAPPE_DOCKER_REF)"
	@echo "frappe_docker is at the pinned commit $(FRAPPE_DOCKER_REF)."

erp-preflight:
	@test -f .env || { echo ".env missing. Run 'make setup' first."; exit 1; }
	@test -n "$(call env_value,ERPNEXT_ADMIN_PASSWORD)" \
		|| { echo "ERPNEXT_ADMIN_PASSWORD is blank in .env. Run 'make env-secrets'."; exit 1; }
	@v=$$(docker compose version --short 2>/dev/null | sed 's/^v//'); \
	if [ -z "$$v" ] || [ "$$(printf '%s\n' "$(ERP_MIN_COMPOSE)" "$$v" | sort -V | head -n 1)" != "$(ERP_MIN_COMPOSE)" ]; then \
		echo "Docker Compose $(ERP_MIN_COMPOSE) or newer is needed (found: $${v:-none})."; exit 1; \
	fi

erp-up: erp-clone erp-preflight ## Start ERPNext, replace the default admin password, wait until it answers
	@$(ERP_COMPOSE) up -d
	@echo "Waiting for create-site to finish. The first run takes several minutes (follow with: make erp-logs)."
	@cid=$$($(ERP_COMPOSE) ps -a -q create-site); \
	code=$$(timeout 900 docker wait "$$cid") || { echo "create-site did not finish within 15 minutes."; exit 1; }; \
	if [ "$$code" != "0" ]; then \
		echo "create-site failed (exit $$code). Check: make erp-logs"; exit 1; \
	fi
	@# The password goes in on stdin, so it never appears in this terminal or in host process arguments.
	@printf '%s\n' "$(call env_value,ERPNEXT_ADMIN_PASSWORD)" \
		| $(ERP_COMPOSE) exec -T backend bash -c \
			'IFS= read -r pw; bench --site frontend set-admin-password "$$pw"' >/dev/null
	@echo "Administrator password set from .env (pwd.yml's default 'admin' no longer works)."
	@port="$(call env_value,ERPNEXT_PORT)"; port=$${port:-8080}; \
	for i in $$(seq 1 60); do \
		if curl -fsS "http://127.0.0.1:$$port/api/method/ping" 2>/dev/null | grep -q pong; then \
			echo "ERPNext is up: http://localhost:$$port (log in as Administrator)"; exit 0; \
		fi; \
		sleep 10; \
	done; \
	echo "ERPNext did not answer on port $$port within 10 minutes. Check: make erp-logs"; exit 1

erp-down: erp-clone ## Stop ERPNext (keeps its volumes and data)
	@$(ERP_COMPOSE) down

erp-logs: erp-clone ## Follow ERPNext logs
	@$(ERP_COMPOSE) logs -f

erp-ps: erp-clone ## Show each ERPNext service and its status
	@$(ERP_COMPOSE) ps -a

erp-check: ## Run the live ERPNext checks
	@uv run pytest -m integration tests/integration/test_erpnext.py -v
