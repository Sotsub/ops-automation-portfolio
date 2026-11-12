# infra: shared Docker stack

The reporting and automation stack for Bluefield Supply Co. (a fictional company; demo data only).
It is defined in [`docker-compose.yml`](docker-compose.yml). ERPNext runs separately from the official
[frappe_docker](https://github.com/frappe/frappe_docker) repository and is not part of this file.
See [ERPNext](#erpnext) below.

| Service | Profile | Image | URL (from the Codespace) | Purpose |
| --- | --- | --- | --- | --- |
| Postgres | core | `postgres:18.6-alpine` | `localhost:5432` | Reporting database plus app databases for Metabase and n8n |
| Mailpit | core | `axllent/mailpit:v1.33.0` | http://localhost:8025 (SMTP on `localhost:1025`) | Catches test email; nothing is really sent |
| Metabase | reporting | `metabase/metabase:v0.64.5.4` | http://localhost:3000 | Dashboards |
| n8n | automation | `docker.n8n.io/n8nio/n8n:2.46.6` | http://localhost:5678 | Schedules and workflow automation |
| ERPNext | erp | `frappe/erpnext:v16.54.0` (via frappe_docker) | http://localhost:8080 | The ERP. See [ERPNext](#erpnext) |

Every port binds to `127.0.0.1`, so the services are reachable only from inside the Codespace (or
through VS Code's private port forwarding). Image versions are pinned and were checked on 2026-11-06.

## Profiles: start only what you need

Every running service uses Codespaces hours and memory, so the default is the smallest stack. See
[docs/free-tier-limits.md](../docs/free-tier-limits.md) for what each allowance covers.

| Profile | Services | Start | Stop |
| --- | --- | --- | --- |
| core | Postgres, Mailpit | `make up` | `make down` (stops all profiles) |
| reporting | Metabase | `make up-reporting` (also starts core) | `make stop-reporting` |
| automation | n8n | `make up-automation` (also starts core) | `make stop-automation` |
| erp | ERPNext | `make erp-up` | `make erp-down` |
| everything but ERPNext | | `make up-all` | `make down` |

Core services have no `profiles:` key in `docker-compose.yml`, so they always start. That's deliberate:
Metabase and n8n depend on Postgres, and Compose won't start a dependency that sits behind a disabled
profile. ERPNext isn't a Compose profile in this file. It runs from frappe_docker's `pwd.yml` as its own
project, `bluefield-erp`, and the `erp-*` targets manage it the same way.

## How Postgres is laid out

One Postgres server holds three databases, each with its own login:

| Database | Owner / login | Contents |
| --- | --- | --- |
| `bluefield` | `bluefield_admin` | Business data in schemas `raw`, `staging`, `marts`, `ops`, and the approved `ai` views |
| `metabase` | `metabase` | Metabase's own settings, users, and saved dashboards |
| `n8n` | `n8n` | n8n's workflows, credentials, and execution history |

Metabase and n8n can't connect to `bluefield` with their app logins. Metabase reads the `marts` schema
through `reporting_reader`, and the AI assistant reads the approved `ai` views through `ai_reader`.
Both logins are read-only and can't see `raw`, `staging` or `ops` (see [`assistant/README.md`](../assistant/README.md) and
[`pipeline/README.md`](../pipeline/README.md)). [`postgres/init/10-bluefield.sh`](postgres/init/10-bluefield.sh)
creates all of this. Postgres runs it automatically the first time it starts with an empty volume.
It is safe to rerun with `make db-init`.

## The Codespace (dev container)

[`.devcontainer/devcontainer.json`](../.devcontainer/devcontainer.json) defines the Codespace, so a new one
comes up ready to use:

- Python 3.12 image (`mcr.microsoft.com/devcontainers/python:3.3.2-3.12-bookworm`)
- Docker inside the container (`docker-in-docker:4.1.3`). Its data lives in a Docker volume that
  survives container rebuilds.
- uv `0.13.0`, the same version CI uses. `make setup` runs automatically after creation.
- Labelled ports in the Ports tab: Metabase 3000, n8n 5678, Mailpit 8025, ERPNext 8080. They stay
  **Private**. Postgres (5432) and SMTP (1025) are never auto-forwarded.
- VS Code extensions: Python, Ruff, and Claude Code

To start one, use VS Code's **Codespaces: Create New Codespace**, then pick this repository, branch `main`,
and **2-core**. A Codespace created before this file existed doesn't pick it up automatically. Create a new
one, then delete the old one, because both count toward the 15 GB storage allowance. Push any work first.
The new Codespace starts with empty Docker volumes and no `.env`. Run `make env-secrets` and start fresh,
and redo the browser setup below. All demo data is recreated by script, so nothing is lost.

## First-time setup

Run these in the Codespace terminal from the repository root. The 2-core machine is enough for this stack.

```bash
make setup         # already run by the dev container; safe to repeat
make env-secrets   # fills blank stack passwords and keys in .env with random values
make up-all        # starts all four services and waits until each one is healthy
make check-stack   # live checks: schemas, permissions, health endpoints, test email
```

For daily work, `make up` (core only) is usually enough. `make check-stack` skips the Metabase and n8n
checks when their profile isn't running, and fails if they're running but unhealthy.

`make env-secrets` never prints secrets and never overwrites a value that's already set. If you already
have a `.env` from an earlier step, it adds the missing keys. Copy any other new settings you want
to change from `.env.example`. The defaults work without them.

The first `make up-all` downloads the images and runs Metabase's database migrations, so it can take
several minutes. Later starts are faster.

### Finish the browser setup

1. Open the **Ports** tab in VS Code and open ports 3000, 5678, and 8025. Leave their visibility **Private**.
2. **Metabase (3000):** Don't create the admin account by hand. Run `make dashboards`. It finishes
   Metabase's setup with `METABASE_ADMIN_EMAIL` and `METABASE_ADMIN_PASSWORD` from `.env`, connects it to
   `marts` as the read-only `reporting_reader`, and builds the dashboards (see
   [`pipeline/README.md`](../pipeline/README.md)). Then sign in with that email and password.
3. **n8n (5678):** Create the owner account.
4. **Mailpit (8025):** No login. The check email from `make check-stack` should be in the inbox.

Store these admin passwords in a password manager, not in the repository.

## Daily use

| Command | What it does |
| --- | --- |
| `make up` | Start the core profile (Postgres, Mailpit) and wait for its health checks |
| `make up-reporting` / `make up-automation` | Add Metabase / n8n (core starts too) |
| `make up-all` | Start every stack service |
| `make stop-reporting` / `make stop-automation` | Stop just Metabase / n8n. Core keeps running |
| `make ps` | Show each service in every profile, and its health |
| `make logs` | Follow all logs (`Ctrl+C` to stop following) |
| `make check-stack` | Run the live checks in `tests/integration/test_stack.py` |
| `make down` | Stop and remove the containers in every profile. Data volumes are kept |
| `make db-init` | Rerun the Postgres init script after changing it |

Without `make`, use `docker compose -f infra/docker-compose.yml --env-file .env <command>` from the
repository root. Add `--profile reporting` or `--profile automation` to include those services.

**Stop the stack, then stop the Codespace, when you finish.** A stopped Codespace uses no compute hours.
The volumes still count toward the 15 GB storage allowance.

## Troubleshooting

| Symptom | Likely cause and fix |
| --- | --- |
| `required variable POSTGRES_PASSWORD is missing a value` (or another secret) | Run `make env-secrets`. |
| `make up` (or `up-*`) stops with `container ... is unhealthy` | Run `make ps` to find the service, then `docker compose -f infra/docker-compose.yml --env-file .env logs <service>`. |
| `make check-stack` shows Metabase or n8n as skipped | Their profile isn't running. Start it with `make up-reporting` or `make up-automation`, or use `make up-all`. |
| Metabase takes a long time to become healthy | The first start runs migrations. Watch `make logs`. It's still working while the log keeps moving. On a 2-core machine, close other heavy services. |
| Postgres logs mention `/var/lib/postgresql/data` or an old data format | Postgres 18 keeps data in `/var/lib/postgresql/18/docker`. An old volume from another major version won't load. Reset the volumes (below). |
| `password authentication failed for user "metabase"` or `"n8n"` | `.env` changed after the volume was created. Run `make db-init` to apply the current passwords, then `docker compose -f infra/docker-compose.yml --env-file .env restart metabase n8n`. |
| Schemas are missing after you edited the init script | Init scripts run only on an empty volume. Run `make db-init`. |
| `port is already allocated` | Another process uses that port. Change `POSTGRES_PORT`, `METABASE_PORT`, `N8N_PORT`, `MAILPIT_UI_PORT`, or `MAILPIT_SMTP_PORT` in `.env`. |
| n8n says saved credentials can't be decrypted | `N8N_ENCRYPTION_KEY` changed. Restore the old key, or reset the n8n data. |
| You want a completely fresh stack | `docker compose -f infra/docker-compose.yml --env-file .env --profile reporting --profile automation down -v` **deletes all stack data** (dashboards, workflows, emails, database), then `make up-all`. Include both `--profile` flags, or the Metabase and n8n containers keep running. |

## ERPNext

ERPNext runs from the official frappe_docker demo file, `pwd.yml`, which is used unchanged.

| Piece | Where it lives |
| --- | --- |
| frappe_docker clone | `../frappe_docker`, next to this repo and **outside it**, so it can never be committed. Override the path with `make erp-up FRAPPE_DOCKER_DIR=/some/other/path`. |
| Pinned version | `FRAPPE_DOCKER_REF` in the [Makefile](../Makefile): frappe_docker commit `46c7ced` (2026-11-06), whose `pwd.yml` runs `frappe/erpnext:v16.54.0`, `mariadb:11.8`, and `redis:6.2-alpine` |
| Bluefield override | [`erpnext/compose.override.yml`](erpnext/compose.override.yml) |
| Compose project | `bluefield-erp`, which keeps its containers, volumes, and network separate from the `bluefield` stack |
| URL | http://localhost:8080 (`ERPNEXT_PORT` in `.env`) |

**Ports.** In `pwd.yml`, only the `frontend` (nginx) service publishes a port, `8080`, and it binds to every
network interface. The override replaces that with `127.0.0.1:${ERPNEXT_PORT}`, so ERPNext follows the same
localhost-only rule as the rest of the stack. MariaDB and Redis stay inside the Docker network. Port 8080
doesn't clash with the stack's ports (5432, 3000, 5678, 8025, 1025). The override uses Compose's `!override`
tag, which needs Docker Compose 2.24.4 or newer. `make erp-up` checks the version first.

**Login.** `pwd.yml` creates the site with `Administrator` / `admin`. Right after the site is created,
`make erp-up` replaces that password with `ERPNEXT_ADMIN_PASSWORD` from `.env`. The value is sent on stdin
and never printed. The MariaDB root password in `pwd.yml` is still `admin`. That's acceptable only because
the database can't be reached from outside the Docker network, and it's a known limitation of this
disposable demo setup.

### Start ERPNext

From the repository root in the Codespace:

```bash
make env-secrets   # adds ERPNEXT_ADMIN_PASSWORD to .env and keeps the existing values
make erp-up        # clone/pin frappe_docker, pull each image once, start, create the site, set password, run the setup wizard
make erp-check     # live checks: ping, the .env password works, the default "admin" is rejected
```

To load the demo data next, see [`erp/README.md`](../erp/README.md) (`make erp-api-keys`, then `make erp-seed`).

The first `make erp-up` downloads the images and creates the site, which can take 5 to 10 minutes.
The ERPNext image is about 1 GB to download and 4.6 GB on disk, so check that `df -h /` shows at least
6 GB free first. It ends with `ERPNext is up: http://localhost:8080`.

Then, in VS Code's **Ports** tab, open port 8080 and keep it **Private**. Log in as `Administrator` with
`ERPNEXT_ADMIN_PASSWORD` (open `.env` yourself to copy it). The login form's **Email** box also accepts the
username, so type `Administrator` there.

You don't need to click through ERPNext's setup wizard. `make erp-up` runs `make erp-setup`, which
answers it from [`erpnext/setup_wizard.json`](erpnext/setup_wizard.json): **Bluefield Supply Co.**, United
States, USD, America/New_York time, with the Accounting and Stock modules. This is a disposable demo
site that the seed script fills, so don't enter anything by hand that you need to keep.

**Machine size.** ERPNext alone runs on the 2-core Codespace. To run it alongside the shared stack
(`make up`), switch to the 4-core machine, and stop whichever you aren't using.

| Command | What it does |
| --- | --- |
| `make erp-up` | Start ERPNext (safe to rerun; an existing site is kept) |
| `make erp-pull` | Download each ERPNext image once and skip images already present. `make erp-up` runs it first |
| `make erp-setup` | Answer the setup wizard from `erpnext/setup_wizard.json`. Does nothing if setup is already done. `make erp-up` runs it |
| `make erp-api-keys` | Create the integration user and write its API key to `.env` (see [`erp/README.md`](../erp/README.md)) |
| `make erp-seed` | Load the fictional demo data (see [`erp/README.md`](../erp/README.md)) |
| `make erp-seed-check` | Run the live checks on the seeded data in `tests/integration/test_erp_seed.py` |
| `make erp-ps` | Show each ERPNext service. `configurator` and `create-site` should be `Exited (0)` |
| `make erp-logs` | Follow ERPNext logs |
| `make erp-check` | Run the live checks in `tests/integration/test_erpnext.py` |
| `make erp-down` | Stop and remove the ERPNext containers. Volumes (site and database) are kept |

### ERPNext troubleshooting

| Symptom | Likely cause and fix |
| --- | --- |
| `Docker Compose 2.24.4 or newer is needed` | Update Docker Compose. Codespaces images normally already have a newer version. |
| `ERPNEXT_ADMIN_PASSWORD is blank in .env` | Run `make env-secrets`. |
| `create-site failed` | Run `make erp-logs` and look at the `create-site` lines. It's usually a timeout waiting for MariaDB on a busy machine. Run `make erp-up` again. |
| `no space left on device` while pulling or extracting a layer | The disk is full. Check with `df -h /`. Stop the shared stack (`make down`), run `uv cache clean`, then `make erp-up` again. `make erp-pull` downloads each image once, because Compose on its own pulls the shared ERPNext image once per service, and with Docker's containerd image store each of those pulls unpacks its own copy. |
| `Invalid Login` on the ERPNext login page | Only `Administrator` exists on a new site, and personal email or Google accounts don't work. Type `Administrator` in the Email box and use `ERPNEXT_ADMIN_PASSWORD` from `.env`. `make erp-check` confirms the password works. |
| `port is already allocated` on 8080 | Something else uses 8080. Set `ERPNEXT_PORT` (and `ERPNEXT_URL`) in `.env` to a free port, then `make erp-up`. |
| `checkout` error in `erp-clone` | The clone at `../frappe_docker` has local edits. This repo never edits it, so run `git -C ../frappe_docker status` and discard the changes. |
| You want a fresh site, for example after changing `erpnext/setup_wizard.json` | `docker compose -p bluefield-erp -f ../frappe_docker/pwd.yml -f infra/erpnext/compose.override.yml --env-file .env down -v` **deletes the ERPNext site and database**. Then run `make erp-up` (setup runs automatically), `make erp-api-keys` and `make erp-seed`. |
