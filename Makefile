# Bluefield Supply Co. portfolio: common commands.
# Runs in GitHub Codespaces or any Linux/macOS shell with GNU make.

COMPOSE_FILE := infra/docker-compose.yml
COMPOSE := docker compose -f $(COMPOSE_FILE) --env-file .env
# Compose profiles (see infra/docker-compose.yml). Core (postgres, mailpit) has no profile and always runs.
# ALL_PROFILES is spelled out instead of --profile "*" so it works on any Compose v2 release.
REPORTING_SERVICES := metabase
AUTOMATION_SERVICES := n8n
ALL_PROFILES := --profile reporting --profile automation
UP_WAIT := up -d --wait --wait-timeout 420
SECRET_KEYS := POSTGRES_PASSWORD METABASE_DB_PASSWORD N8N_DB_PASSWORD MB_ENCRYPTION_SECRET_KEY N8N_ENCRYPTION_KEY ERPNEXT_ADMIN_PASSWORD \
	REPORTING_READER_PASSWORD METABASE_ADMIN_PASSWORD AI_READER_PASSWORD

# ERPNext runs from the official frappe_docker pwd.yml. The clone lives OUTSIDE this repository
# (next to it by default), so it can never be committed here.
FRAPPE_DOCKER_DIR ?= $(CURDIR)/../frappe_docker
# frappe_docker main on 2026-11-06. Its pwd.yml pins frappe/erpnext:v16.54.0. Change deliberately.
FRAPPE_DOCKER_REF := 46c7ced81efbd4a119e14b81bf78e3b77cad3309
ERP_PROJECT := bluefield-erp
ERP_COMPOSE := docker compose -p $(ERP_PROJECT) -f "$(FRAPPE_DOCKER_DIR)/pwd.yml" -f infra/erpnext/compose.override.yml --env-file .env
ERP_MIN_COMPOSE := 2.24.4
ERP_SETUP_FILE := infra/erpnext/setup_wizard.json
# Shell snippet that reads one key from .env without sourcing the file or printing the value.
env_value = $$(sed -n 's/^$(1)=//p' .env | tail -n 1 | tr -d '\r')

.DEFAULT_GOAL := help
.PHONY: help setup lint format test test-all up up-reporting up-automation up-all stop-reporting \
	stop-automation down logs ps check-stack db-init env-secrets check-compose \
	erp-clone erp-preflight erp-pull erp-up erp-setup erp-api-keys erp-seed erp-seed-check pipeline-run pipeline-check dashboards dashboards-check ask assistant-eval assistant-check erp-down erp-logs erp-ps erp-check

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-16s %s\n", $$1, $$2}'

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
		v=$$(openssl rand -hex 32 2>/dev/null || python3 -c 'import secrets; print(secrets.token_hex(32))'); \
		test -n "$$v" || { echo "Could not generate a random value (need openssl or python3)."; exit 1; }; \
		if grep -q "^$$k=." .env; then echo "$$k: already set, kept"; \
		elif grep -q "^$$k=$$" .env; then sed -i "s|^$$k=$$|$$k=$$v|" .env; echo "$$k: generated"; \
		else echo "$$k=$$v" >> .env; echo "$$k: generated"; fi; \
	done

up: check-compose ## Start the core stack only (Postgres, Mailpit) and wait until healthy
	@$(COMPOSE) $(UP_WAIT)

up-reporting: check-compose ## Start core + reporting profile (Metabase)
	@$(COMPOSE) --profile reporting $(UP_WAIT)

up-automation: check-compose ## Start core + automation profile (n8n)
	@$(COMPOSE) --profile automation $(UP_WAIT)

up-all: check-compose ## Start core + reporting + automation (use a 4-core Codespace with ERPNext)
	@$(COMPOSE) $(ALL_PROFILES) $(UP_WAIT)

stop-reporting: check-compose ## Stop the reporting profile only (Metabase); core keeps running
	@$(COMPOSE) --profile reporting stop $(REPORTING_SERVICES)

stop-automation: check-compose ## Stop the automation profile only (n8n); core keeps running
	@$(COMPOSE) --profile automation stop $(AUTOMATION_SERVICES)

down: check-compose ## Stop and remove every stack service, all profiles (keeps data volumes)
	@$(COMPOSE) $(ALL_PROFILES) down

logs: check-compose ## Follow logs from every running stack service
	@$(COMPOSE) $(ALL_PROFILES) logs -f

ps: check-compose ## Show each stack service (all profiles) and its health status
	@$(COMPOSE) $(ALL_PROFILES) ps -a

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

# pwd.yml uses one image for 8 services. Left to itself, `compose up` pulls it once per service in
# parallel, and with Docker's containerd image store each pull unpacks its own copy of the layers,
# which filled a 32 GB Codespace disk. So pull each distinct image once, skipping ones already here.
erp-pull: erp-clone erp-preflight ## Download each ERPNext image once (skips images already present)
	@for img in $$($(ERP_COMPOSE) config --images | sort -u); do \
		docker image inspect "$$img" >/dev/null 2>&1 && continue; \
		echo "Pulling $$img"; \
		docker pull -q "$$img" >/dev/null || { echo "Could not pull $$img. Check the network and free disk (df -h /)."; exit 1; }; \
	done

# A new site has no encryption_key until something needs one, and Frappe's web workers each cache
# the site config (get_site_config(cached=is_request)). So the first API key made through the web
# had several workers each generate and save their own key, and the secret then failed to decrypt.
# Fix: create the key once with bench, then restart the backend so every worker reads it. The
# frontend proxy is restarted after it so it picks up the backend's new address.
erp-up: erp-pull ## Start ERPNext, replace the default admin password, wait until it answers
	@$(ERP_COMPOSE) up -d --pull never
	@echo "Waiting for create-site to finish. The first run takes several minutes (follow with: make erp-logs)."
	@cid=$$($(ERP_COMPOSE) ps -a -q create-site); \
	code=$$(timeout 900 docker wait "$$cid") || { echo "create-site did not finish within 15 minutes."; exit 1; }; \
	if [ "$$code" != "0" ]; then \
		echo "create-site failed (exit $$code). Check: make erp-logs"; exit 1; \
	fi
	@$(ERP_COMPOSE) exec -T backend bench --site frontend execute frappe.utils.password.get_encryption_key >/dev/null \
		|| { echo "Could not create the site's encryption key. Check: make erp-logs"; exit 1; }
	@$(ERP_COMPOSE) restart backend >/dev/null 2>&1 && $(ERP_COMPOSE) restart frontend >/dev/null 2>&1 \
		|| { echo "Could not restart the ERPNext web services. Check: make erp-ps"; exit 1; }
	@# The password goes in on stdin, so it never appears in this terminal or in host process arguments.
	@printf '%s\n' "$(call env_value,ERPNEXT_ADMIN_PASSWORD)" \
		| $(ERP_COMPOSE) exec -T backend bash -c \
			'IFS= read -r pw; bench --site frontend set-admin-password "$$pw"' >/dev/null
	@echo "Administrator password set from .env (pwd.yml's default 'admin' no longer works)."
	@port="$(call env_value,ERPNEXT_PORT)"; port=$${port:-8080}; \
	for i in $$(seq 1 60); do \
		if curl -fsS "http://127.0.0.1:$$port/api/method/ping" 2>/dev/null | grep -q pong; then exit 0; fi; \
		sleep 10; \
	done; \
	echo "ERPNext did not answer on port $$port within 10 minutes. Check: make erp-logs"; exit 1
	@$(MAKE) --no-print-directory erp-setup
	@port="$(call env_value,ERPNEXT_PORT)"; echo "ERPNext is up: http://localhost:$${port:-8080} (log in as Administrator)"

# Answers the setup wizard from a file, so a new site is always the same US company in USD.
# ERPNext's setup_complete() returns early when setup is already done, so this is safe to rerun.
erp-setup: erp-clone erp-preflight ## Finish ERPNext's setup wizard from infra/erpnext/setup_wizard.json (skips if done)
	@args=$$(python3 -c 'import json, sys; print(json.dumps({"args": json.load(open(sys.argv[1]))}))' $(ERP_SETUP_FILE)) \
		|| { echo "Could not read $(ERP_SETUP_FILE)."; exit 1; }; \
	$(ERP_COMPOSE) exec -T backend bench --site frontend execute \
		frappe.desk.page.setup_wizard.setup_wizard.setup_complete --kwargs "$$args" >/dev/null \
		|| { echo "The setup wizard failed. Check: make erp-logs"; exit 1; }
	@done=$$($(ERP_COMPOSE) exec -T backend bench --site frontend execute frappe.is_setup_complete 2>/dev/null | tail -n 1); \
	test "$$done" = "true" || { echo "Setup is still not complete. Check: make erp-logs"; exit 1; }
	@echo "ERPNext setup is complete (answers from $(ERP_SETUP_FILE))."

erp-api-keys: ## Create the ERPNext integration user and write its API key to .env (never printed)
	@uv run python -m erp.api_user

erp-seed: ## Load the fictional Bluefield demo data into ERPNext (safe to rerun; ARGS="--dry-run" to preview)
	@uv run python -m erp.seed $(ARGS)

erp-seed-check: ## Run the live checks on the seeded data in tests/integration/test_erp_seed.py
	@uv run pytest -m integration tests/integration/test_erp_seed.py -v

erp-down: erp-clone ## Stop ERPNext (keeps its volumes and data)
	@$(ERP_COMPOSE) down

erp-logs: erp-clone ## Follow ERPNext logs
	@$(ERP_COMPOSE) logs -f

erp-ps: erp-clone ## Show each ERPNext service and its status
	@$(ERP_COMPOSE) ps -a

erp-check: ## Run the live ERPNext checks
	@uv run pytest -m integration tests/integration/test_erpnext.py -v

# --- Project 1: ERP-to-reporting pipeline ---------------------------------------------------------

pipeline-run: ## Load ERPNext into Postgres (raw) and build staging + marts with dbt (ARGS="--full" etc.)
	@uv run python -m pipeline.run $(ARGS)

pipeline-check: ## Run the live pipeline checks (reconciles marts with ERPNext)
	@uv run pytest -m integration tests/integration/test_pipeline.py -v

dashboards: ## Create or update the Project 1 Metabase dashboards (needs make up-reporting)
	@uv run python -m pipeline.metabase_setup

dashboards-check: ## Run the live dashboard checks (Metabase figures equal the marts)
	@uv run pytest -m integration tests/integration/test_dashboards.py -v

# --- Project 2: AI reporting assistant --------------------------------------------------------------

ask: ## Ask the AI reporting assistant a question: make ask Q="Who pays late most often?"
	@test -n "$(Q)" || { echo 'Usage: make ask Q="your question"'; exit 1; }
	@uv run python -m assistant.ask "$(Q)"

assistant-eval: ## Run the assistant's evaluation questions against the live model (uses free-tier quota)
	@uv run python -m assistant.eval $(ARGS)

assistant-check: ## Run the live checks on the assistant's data access (no AI model needed)
	@uv run pytest -m integration tests/integration/test_assistant.py -v
