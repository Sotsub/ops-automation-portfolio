# Project 1: ERP-to-dashboard pipeline

> **Demo data only.** Everything here reports on Bluefield Supply Co., a fictional distributor,
> using the data that [`make erp-seed`](../erp/README.md) puts in ERPNext.

The pipeline copies ERPNext's sales, purchasing, payment and stock records into the Postgres
reporting database. dbt then turns them into tested reporting tables, and two Metabase dashboards
read those tables. Every number on a dashboard is calculated in SQL and checked against ERPNext.

```
ERPNext ──REST API──▶ raw.*  ──dbt──▶ staging.*  ──dbt──▶ marts.*  ──▶ Metabase
  (seeded)          19 tables       10 views           8 tables      2 dashboards, 19 questions
                         │                                  ▲
                         └── ops.pipeline_runs, ops.pipeline_watermarks      reporting_reader
                                                                        (read-only, marts only)
```

## Run it

ERPNext and Postgres must be running and ERPNext seeded. The 4-core Codespace runs everything at once.
On the 2-core machine, load the data first, then stop ERPNext before starting Metabase.

```bash
make env-secrets      # adds REPORTING_READER_PASSWORD and METABASE_ADMIN_PASSWORD to .env if blank
make up               # Postgres (recreate it after env-secrets so it sees the new password)
make db-init          # creates the reporting_reader login (safe to rerun)
make erp-up           # ERPNext, already seeded with make erp-api-keys and make erp-seed
make pipeline-run     # ERPNext -> raw -> staging -> marts (about 10 seconds)
make pipeline-check   # live checks: marts reconcile with ERPNext, access rules hold

make up-reporting     # Metabase
make dashboards       # create or update the dashboards
make dashboards-check # live checks: Metabase shows the same numbers as the marts
```

`make dashboards` prints a link to each dashboard. In VS Code's **Ports** tab, open port 3000 and
keep it **Private**. Sign in with `METABASE_ADMIN_EMAIL` (default `admin@example.com`) and
`METABASE_ADMIN_PASSWORD` from `.env` (open the file yourself to copy it).

| Command | What it does |
| --- | --- |
| `make pipeline-run` | Incremental load (only records changed since the last run), then `dbt build` |
| `make pipeline-run ARGS="--full"` | Rebuild every raw table from scratch. Use it after deleting records in ERPNext |
| `make pipeline-run ARGS="--skip-dbt"` | Load raw tables only |
| `make pipeline-run ARGS="--dbt-only"` | Rebuild staging and marts from what is already in raw |
| `make dashboards` | Set up Metabase on first run, then create or update every question and dashboard |

Everything is safe to rerun. Loads are upserts, dbt rebuilds its tables, and `make dashboards`
matches questions and dashboards by name, so it updates them instead of adding copies.

## What gets built

**Raw** (`pipeline/extract.py`). There's one table per ERPNext doctype, such as
`raw.erpnext_sales_invoice`. Each row holds the record exactly as the API returned it, in a `data`
jsonb column, alongside its `name`, `modified`, `docstatus` and the `run_id` that loaded it.

- **Incremental.** Each doctype has a watermark in `ops.pipeline_watermarks`, the newest ERPNext
  `modified` timestamp loaded so far. The next run asks only for records modified since then.
- **Child rows go with their parent.** When a payment marks an invoice as paid, ERPNext updates the
  invoice's timestamp but not its lines' timestamps. So the loader always reloads the lines of
  every invoice it fetches, and lines removed from a draft disappear too.
- **One transaction per doctype.** If a run fails, every table is left as it was before that
  doctype started, and the watermark doesn't move.

**Staging** (`pipeline/dbt/models/staging`). These views type the JSON fields. Transactions keep
submitted documents only, so drafts and cancelled documents don't count.

**Marts** (`pipeline/dbt/models/marts`). These are the tables the dashboards read:

| Table | One row per | Used for |
| --- | --- | --- |
| `sales_lines` | invoice line | Revenue, cost (at ERPNext's valuation) and gross margin |
| `sales_monthly` | month × customer group × region × product group | Trends and mix |
| `customers` | customer | Revenue, average days to pay, % paid late, open and overdue balance |
| `ar_open_invoices` | unpaid invoice | Days overdue and aging bucket |
| `ar_aging` | aging bucket (all five) | Receivables aging chart |
| `inventory_status` | product | On hand compared with reorder level, 90-day demand, days of cover |
| `supplier_spend_monthly` | month × supplier | Purchasing spend |
| `kpi_summary` | one row | Headline numbers and data freshness |

Overdue days and "last 90 days" are measured from `as_of_date`, which is today unless you pin it:
`make pipeline-run ARGS="--dbt-only"` after setting `as_of_date` in
[`dbt/dbt_project.yml`](dbt/dbt_project.yml).

**Tests.** `dbt build` runs 43 data tests on every run:

- keys are unique and not empty
- every line belongs to an invoice and an existing product
- the allowed values for aging buckets and stock statuses
- reconciliations: invoice lines add up to invoice totals, the aging chart accounts for every
  open dollar, and the monthly figures equal the line-level figures

If any test fails, the run is marked `failed` in `ops.pipeline_runs`.

## Access rules

| Login | Can do |
| --- | --- |
| `bluefield_admin` | Everything. The pipeline and dbt write `raw`, `staging`, `marts` and `ops` |
| `reporting_reader` | Read `marts` only. It has no access to `raw`, `staging` or `ops`, and every session is read-only. Metabase connects as this login, and Project 2's AI assistant will too |

dbt grants `SELECT` on each mart to `reporting_reader` whenever it rebuilds the table
(`+grants` in `dbt_project.yml`). Metabase is also limited to the `marts` schema in its database
settings.

## Dashboards

Both live in the **Bluefield Supply Co. (demo)** collection, and each opens with a demo-data note.

- **Sales Overview (demo):** revenue, gross margin %, invoices, monthly revenue and margin,
  revenue by customer group and by region, product-group margins, the top 10 customers, and when
  the data was loaded.
- **Cash and Inventory (demo):** open and overdue receivables, the receivables aging chart,
  overdue invoices to chase, the customers who pay late most often, open payables, monthly
  supplier spend, and items to reorder.

The questions are defined in [`dashboards.py`](dashboards.py). Each one only selects, sorts or
totals figures from `marts`, and a test enforces that.

## Not included yet

- **Schedule.** A Codespace isn't always running, so you start `make pipeline-run` yourself.
  Scheduling it with n8n is planned for a later project.
- **Deletes in ERPNext.** An incremental run doesn't notice a record deleted in ERPNext. Submitted
  documents are cancelled, not deleted, and cancellations are picked up. Run with `--full` to
  rebuild from scratch.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `REPORTING_READER_PASSWORD is not set` from `make db-init` | Run `make env-secrets`, then `make up` (Postgres must restart to see the new variable), then `make db-init`. |
| `POSTGRES_PASSWORD ... blank` or a connection refused on port 5432 | Run `make up`. |
| `ERPNEXT_API_KEY/SECRET are blank` | Run `make erp-api-keys`. |
| `dbt build failed` in the log | The log lists each failing model or test and its message. Run `make pipeline-run ARGS="--dbt-only"` after fixing the cause. |
| `make dashboards` fails to sign in | The Metabase admin was created with a different password. If Metabase holds nothing you need, reset its app database, which deletes Metabase's settings and dashboards: `make stop-reporting`, then `docker compose -f infra/docker-compose.yml --env-file .env exec postgres dropdb -U bluefield_admin metabase`, then `make db-init`, `make up-reporting` and `make dashboards`. |
| A dashboard shows old numbers | Run `make pipeline-run`. The **Data as of** card shows when ERPNext was last loaded. |
