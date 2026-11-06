# infra: shared Docker stack

The reporting and automation stack for Bluefield Supply Co. (a fictional company; demo data only).
It is defined in [`docker-compose.yml`](docker-compose.yml). ERPNext runs separately from the official
[frappe_docker](https://github.com/frappe/frappe_docker) repository and is not part of this file.

| Service | Image | URL (from the Codespace) | Purpose |
| --- | --- | --- | --- |
| Postgres | `postgres:18.6-alpine` | `localhost:5432` | Reporting database plus app databases for Metabase and n8n |
| Metabase | `metabase/metabase:v0.64.5.4` | http://localhost:3000 | Dashboards |
| n8n | `docker.n8n.io/n8nio/n8n:2.46.6` | http://localhost:5678 | Schedules and workflow automation |
| Mailpit | `axllent/mailpit:v1.33.0` | http://localhost:8025 (SMTP on `localhost:1025`) | Catches test email; nothing is really sent |

Every port binds to `127.0.0.1`, so the services are reachable only from inside the Codespace (or
through VS Code's private port forwarding). Image versions are pinned and were checked on 2026-11-06.

## How Postgres is laid out

One Postgres server holds three databases, each with its own login:

| Database | Owner / login | Contents |
| --- | --- | --- |
| `bluefield` | `bluefield_admin` | Business data in schemas `raw`, `staging`, `marts`, `ops` |
| `metabase` | `metabase` | Metabase's own settings, users, and saved dashboards |
| `n8n` | `n8n` | n8n's workflows, credentials, and execution history |

Metabase and n8n can't connect to `bluefield` with their app logins. In Project 1, Metabase reads the
`marts` schema through a separate read-only user. [`postgres/init/10-bluefield.sh`](postgres/init/10-bluefield.sh)
creates all of this. Postgres runs it automatically the first time it starts with an empty volume.
It is safe to rerun with `make db-init`.

## First-time setup

Run these in the Codespace terminal from the repository root. The 2-core machine is enough for this stack.

```bash
make setup         # Python deps; creates .env from .env.example if it's missing
make env-secrets   # fills blank stack passwords and keys in .env with random values
make up            # starts all four services and waits until each one is healthy
make check-stack   # live checks: schemas, permissions, health endpoints, test email
```

`make env-secrets` never prints secrets and never overwrites a value that's already set. If you already
have a `.env` from an earlier step, it adds the missing keys. Copy any other new settings you want
to change from `.env.example`. The defaults work without them.

The first `make up` downloads the images and runs Metabase's database migrations, so it can take
several minutes. Later starts are faster.

### Finish the browser setup

1. Open the **Ports** tab in VS Code and open ports 3000, 5678, and 8025. Leave their visibility **Private**.
2. **Metabase (3000):** Create the admin account. When it asks you to add data, choose **I'll add my
   data later**. Project 1 connects it to `marts` with a read-only user.
3. **n8n (5678):** Create the owner account.
4. **Mailpit (8025):** No login. The check email from `make check-stack` should be in the inbox.

Store these admin passwords in a password manager, not in the repository.

## Daily use

| Command | What it does |
| --- | --- |
| `make up` | Start the stack and wait for every health check |
| `make ps` | Show each service and its health |
| `make logs` | Follow all logs (`Ctrl+C` to stop following) |
| `make check-stack` | Run the live checks in `tests/integration/test_stack.py` |
| `make down` | Stop and remove the containers. Data volumes are kept |
| `make db-init` | Rerun the Postgres init script after changing it |

Without `make`, use `docker compose -f infra/docker-compose.yml --env-file .env <command>` from the
repository root.

**Stop the stack, then stop the Codespace, when you finish.** A stopped Codespace uses no compute hours.
The volumes still count toward the 15 GB storage allowance.

## Troubleshooting

| Symptom | Likely cause and fix |
| --- | --- |
| `required variable POSTGRES_PASSWORD is missing a value` (or another secret) | Run `make env-secrets`. |
| `make up` stops with `container ... is unhealthy` | Run `make ps` to find the service, then `docker compose -f infra/docker-compose.yml --env-file .env logs <service>`. |
| Metabase takes a long time to become healthy | The first start runs migrations. Watch `make logs`. It's still working while the log keeps moving. On a 2-core machine, close other heavy services. |
| Postgres logs mention `/var/lib/postgresql/data` or an old data format | Postgres 18 keeps data in `/var/lib/postgresql/18/docker`. An old volume from another major version won't load. Reset the volumes (below). |
| `password authentication failed for user "metabase"` or `"n8n"` | `.env` changed after the volume was created. Run `make db-init` to apply the current passwords, then `docker compose -f infra/docker-compose.yml --env-file .env restart metabase n8n`. |
| Schemas are missing after you edited the init script | Init scripts run only on an empty volume. Run `make db-init`. |
| `port is already allocated` | Another process uses that port. Change `POSTGRES_PORT`, `METABASE_PORT`, `N8N_PORT`, `MAILPIT_UI_PORT`, or `MAILPIT_SMTP_PORT` in `.env`. |
| n8n says saved credentials can't be decrypted | `N8N_ENCRYPTION_KEY` changed. Restore the old key, or reset the n8n data. |
| You want a completely fresh stack | `docker compose -f infra/docker-compose.yml --env-file .env down -v` **deletes all stack data** (dashboards, workflows, emails, database), then `make up`. |
