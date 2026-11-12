# ERPNext demo data (seed)

> **All of this data is fictional.** Bluefield Supply Co., its customers, suppliers, products, prices
> and emails (`example.com`) are invented for a portfolio demo. Each seeded record says so in its
> notes, and each transaction carries a `DEMO-...` reference.

`make erp-seed` fills ERPNext with a year of trading for Bluefield Supply Co., a US distributor of
cleaning, paper, packaging and safety supplies. The later projects (dashboards, the AI assistant,
reports) all read this data.

## Run it

From the repository root in the Codespace, with ERPNext stopped or running:

```bash
make erp-up          # start ERPNext; a new site is set up automatically as a US company in USD
make erp-api-keys    # create the integration user and write its API key to .env (never printed)
make erp-seed        # load the demo data: about 10-20 minutes the first time
make erp-seed-check  # live checks: counts, statuses, stock, ledger, and that a rerun adds nothing
```

To see what would be created without touching ERPNext, run `make erp-seed ARGS="--dry-run"`.
To load only the first weeks as a quick trial, run `make erp-seed ARGS="--until 2025-11-30"`, then
`make erp-seed` later to finish.

Each command is safe to rerun:

- `make erp-api-keys` keeps a key that already works and adds any missing roles.
- `make erp-seed` skips everything that already exists. If a run stops partway (a network error,
  a closed laptop, a validation error), run it again and it carries on from where it stopped.

## What it creates

| Data | Amount | Notes |
| --- | --- | --- |
| Customers | 40 | 5 groups (Healthcare, Education, Hospitality, Facilities Management, Retail) across 5 US regions. Each has a payment habit, from prompt to slow |
| Suppliers | 12 | Each item has one default supplier with its own lead time |
| Items | 45 | 5 item groups, with reorder level and reorder quantity set per item |
| Opening balances | 1 stock count, 1 cash entry | On 2025-11-01: opening stock for every item and $150,000 in the Operating Account |
| Sales | About 620 orders, 620 invoices, 580 payments | Nov 2025 to Oct 2026. Busier in August and September, quieter in December. A 4% price increase on 2026-03-01 |
| Purchasing | About 280 orders, 275 bills, 260 payments | Reorders run on Mondays and Thursdays for items at or below their reorder level |

The data is built to give the reports something to find:

- About 40% of invoices are paid after their 30-day due date, and a few are still unpaid and overdue.
- A handful of purchase orders are still open (not yet received).
- Eleven items finish below their reorder level, three of them because their supplier is backordered
  from mid-September.

## How it works

| File | Role |
| --- | --- |
| [`seed_data.py`](seed_data.py) | Builds the dataset in plain Python, with no network. It simulates the year day by day from a fixed random seed, so every run produces identical data. An order only takes stock that is on hand, so stock never goes negative |
| [`seed.py`](seed.py) | Sends the dataset to ERPNext in date order. Each document is saved as a draft and then submitted, the same way the ERPNext screens do it |
| [`client.py`](client.py) | Small REST client: token auth, paging, readable errors. Only reads are retried |
| [`api_user.py`](api_user.py) | Creates `integration@example.com` with the roles the seeder needs and stores its API key in `.env` |
| [`../infra/erpnext/setup_wizard.json`](../infra/erpnext/setup_wizard.json) | The setup wizard answers that `make erp-setup` applies to a new site |

**How reruns find existing records.** Masters are looked up by name. Each transaction stores its
`DEMO-...` key in a standard field, and a rerun looks it up there:

| Document | Field holding the key |
| --- | --- |
| Sales Order, Sales Invoice | Customer's PO No. (`po_no`) |
| Purchase Order | Order Confirmation No. (`order_confirmation_no`) |
| Purchase Invoice | Supplier Invoice No. (`bill_no`) |
| Payment Entry | Reference No. (`reference_no`, ending in `-PAY`) |
| Opening cash (Journal Entry) | Cheque/Reference No. (`cheque_no`) |

**Stock order.** Goods are received in the morning (from 08:00) and shipped in the afternoon (from
12:00), and each stock document on a given day gets its own minute. ERPNext queues a slow stock
revaluation job whenever a new entry is not later than every existing one, so unique times avoid it.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `ERPNEXT_API_KEY or ERPNEXT_API_SECRET is blank` | Run `make erp-api-keys`. |
| `PermissionError ... does not have doctype access` | Run `make erp-api-keys` again. It adds any roles the integration user is missing. |
| `Failed to decrypt key ... Encryption key is invalid` | On a new site, the web workers each generated their own encryption key. `make erp-up` now prevents this by creating the key once with `bench` and restarting the backend. On a site created before that fix, restart the backend and frontend (`make erp-down`, then `make erp-up`), then run `make erp-api-keys` to issue a fresh key. |
| `ERPNext rejected a document` | The log names the step, its `DEMO-...` key and ERPNext's message. Fix the cause, then rerun `make erp-seed`. Finished steps are kept. |
| You want to start again from nothing | `docker compose -p bluefield-erp -f ../frappe_docker/pwd.yml -f infra/erpnext/compose.override.yml --env-file .env down -v` **deletes the ERPNext site**. Then run `make erp-up`, `make erp-api-keys` and `make erp-seed`. |
