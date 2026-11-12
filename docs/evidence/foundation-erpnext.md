# Evidence: ERPNext running in the Codespace (Foundation)

> **Demo environment.** Bluefield Supply Co. is a fictional company. This ERPNext site is a disposable
> demo with no real business data. No passwords or `.env` values appear on this page.

- **Date:** 2026-11-12
- **Where:** GitHub Codespace, 2-core machine, branch `foundation/free-tier-setup`
- **Versions:** `frappe/erpnext:v16.54.0`, `mariadb:11.8`, `redis:6.2-alpine`, frappe_docker pinned at
  `46c7ced81efbd4a119e14b81bf78e3b77cad3309`, Docker Compose 5.6.1 using the containerd image store

## Result

| Check | Command | Result |
| --- | --- | --- |
| ERPNext starts | `make erp-up` | `ERPNext is up: http://localhost:8080` |
| Rerun is safe | `make erp-up` again | Finished in 7 s, pulled nothing, and kept the existing site and company |
| Live checks | `make erp-check` | 3 passed |
| Setup wizard finished | `bench --site frontend execute frappe.is_setup_complete` | `true` |
| Company created | `bench --site frontend execute frappe.get_all --kwargs "{'doctype':'Company','pluck':'name'}"` | `["Bluefield Supply Co."]` |
| Lint | `make lint` | `All checks passed!` |
| Unit tests | `make test` | 51 passed, 9 deselected (integration) |

### `make erp-check`

```text
tests/integration/test_erpnext.py::test_ping_answers_pong PASSED                  [ 33%]
tests/integration/test_erpnext.py::test_admin_login_uses_password_from_env PASSED [ 66%]
tests/integration/test_erpnext.py::test_default_admin_password_is_rejected PASSED [100%]
============================== 3 passed in 0.30s ===============================
```

### ERPNext services after the rerun

```text
bluefield-erp-backend-1        Up About an hour
bluefield-erp-configurator-1   Exited (0)
bluefield-erp-create-site-1    Exited (0)
bluefield-erp-db-1             Up About an hour (healthy)
bluefield-erp-frontend-1       Up About an hour
bluefield-erp-queue-long-1     Up About an hour
bluefield-erp-queue-short-1    Up About an hour
bluefield-erp-redis-cache-1    Up About an hour
bluefield-erp-redis-queue-1    Up About an hour
bluefield-erp-scheduler-1      Up About an hour
bluefield-erp-websocket-1      Up About an hour
```

## Problem found and fixed: the first start filled the disk

The first attempts at `make erp-up` failed with `no space left on device` while extracting an image
layer, even with 12 GB free. The free-space log showed the disk going from 11.6 GB to 0 in about
10 minutes.

**Cause.** `pwd.yml` uses `frappe/erpnext:v16.54.0` for 8 services, and `docker compose config --images`
lists it 8 times. `docker compose up` pulled it once per service, in parallel. With Docker's containerd
image store, each of those pulls unpacked its own copy of the layers, and the largest layer is about
1.3 GB.

**Fix.** A new `make erp-pull` target pulls each distinct image once and skips images already present.
`make erp-up` runs it first, then starts with `up -d --pull never`, so Compose can't start its own
pulls. Two static tests in `tests/test_erpnext_compose.py` check this.

| Run | Lowest free disk during the run | Outcome |
| --- | --- | --- |
| Compose pulls on its own (before the fix) | 0 MB | Failed: `no space left on device` |
| One pull of the image, then `make erp-up` | 10,983 MB | Succeeded in about 2 minutes |
| `make erp-up` rerun with `erp-pull` | 10,883 MB (unchanged) | Succeeded in 7 s, nothing pulled |
