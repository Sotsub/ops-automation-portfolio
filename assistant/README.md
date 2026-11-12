# Project 2: AI reporting assistant

> **Demo data only.** The assistant answers questions about Bluefield Supply Co., a fictional
> distributor. Questions and query results are sent to Google's Gemini free tier, so never point it
> at real data.

Ask a business question in plain English and get a short answer in which every number came from
SQL, with the queries that produced it listed underneath:

```text
$ make ask Q="How much is overdue, and who owes the most?"
As of 2026-11-12, the overdue receivables amount is $9,528.77 across 13 overdue invoices. The
customer with the highest overdue balance is Oak Valley School District, owing $2,433.62.

Sources (demo data, read-only views):
  - get_kpis() -> 1 rows
  - rank_customers(rank_by=overdue_balance, limit=1) -> 1 rows
Number check: passed | status: answered | model: gemini-3.5-flash-lite | run_id: d619074c...
```

## Set it up

1. Get a free Gemini API key at [Google AI Studio](https://aistudio.google.com): **Get API key**,
   then **Create API key**. No billing account is needed.
2. In `.env`, set:
   ```
   AI_PROVIDER=gemini
   AI_MODEL=gemini-3.5-flash-lite
   AI_API_KEY=<your key>
   ```
   `gemini-3.5-flash-lite` answered on the free tier when this was built (2026-11-12). Use an exact
   model name, not a `-latest` alias, so answers don't change when Google moves the alias.
3. Create the assistant's database login and views (safe to rerun):
   ```bash
   make env-secrets     # adds AI_READER_PASSWORD to .env if blank
   make up              # recreate Postgres so it sees the new password
   make db-init         # creates the ai schema and the ai_reader login
   make pipeline-run    # builds the ai views with dbt (ERPNext must be running and seeded)
   ```

## Use it

| Command | What it does |
| --- | --- |
| `make ask Q="Which customers pay late most often?"` | Answer one question |
| `uv run python -m assistant.ask "..." --show-sql` | Also print the SQL of each query |
| `uv run python -m assistant.ask "..." --json` | Print the full result, including every row returned |
| `make assistant-check` | Live checks on the assistant's data access. No AI model is called |
| `make assistant-eval` | Run 14 test questions against the live model (about 5 minutes, about 35 model calls) |

Each answer takes about 5 to 20 seconds on the free tier.

## How it keeps the AI honest

```
question ──▶ model ──picks──▶ approved query ──validated──▶ SQL as ai_reader ──▶ ai.* views
                ▲                                                        │
                └────────────────────── rows ◀───────────────────────────┘
answer ──▶ number check: every figure must match a returned value ──▶ shown, or plain results
   └──▶ ops.assistant_log (question, queries, answer, check result)
```

1. **Approved views only.** dbt builds an `ai` schema of views over the tested marts. They leave
   out anything the assistant doesn't need, such as customer emails. The `ai_reader` login can read
   these views and nothing else: it's refused on `marts`, `raw`, `staging` and `ops`, every session
   is read-only, and any query is stopped after 5 seconds.
2. **The model doesn't write SQL.** It picks one of nine approved queries in
   [`queries.py`](queries.py) and suggests parameter values. Every value is checked: the type, the
   range (a top-N limit of 1 to 20, for example), and the allowed choices. Values are passed as bind
   parameters. Choices that change the SQL, such as which column to rank by, map to fixed SQL text.
   A value that fails a check goes back to the model as an error it can correct.
3. **Every number is checked.** [`grounding.py`](grounding.py) finds each number in the answer. It
   must match a value the queries returned, or a number from the question. Rounding is allowed
   ($9,529, $9.5k and "about $9,500" all match 9,528.77). A figure the model calculated itself,
   such as a new total or a share, fails the check even if the arithmetic is right. Shares are
   instead calculated in SQL (`revenue_share_pct`).
   - If a number fails, the model gets one chance to rewrite the answer.
   - If it fails again, the assistant shows the plain query results instead (status `fallback`).
4. **No write access.** No query or tool can change data. Asked to "mark invoices as paid", the
   assistant says it can only read reports.
5. **Audit log.** Every question is written to `ops.assistant_log`, using the pipeline's admin
   login (`ai_reader` can't write). Each row holds the question, the queries with their arguments
   and row counts, the answer, whether the number check passed, the model, the time taken and the
   tokens used.

## Files

| File | Role |
| --- | --- |
| [`ask.py`](ask.py) | Main loop, command line and audit log |
| [`queries.py`](queries.py) | The nine approved queries and their parameter checks |
| [`grounding.py`](grounding.py) | The number check |
| [`llm.py`](llm.py) | Model interface and the Gemini REST adapter: function calling, and retries that honor `Retry-After` |
| [`eval.py`](eval.py) | Evaluation cases. Expected figures are read from the `ai` views with SQL at run time |
| [`../pipeline/dbt/models/ai`](../pipeline/dbt/models/ai) | The approved views |

**Why plain REST instead of Google's SDK:** the request shape was tested live against the free
tier, it needs no extra dependency, and Google's documentation was moving to a new API at the time.
The adapter is small, and another provider can be added behind `AI_PROVIDER` without changing
`ask.py`.

## Limits

- **Free-tier speed and quota.** Answers take seconds, and Google's free-tier rate limits apply.
  `make assistant-eval` spaces its questions out. On a `429` or `503`, the adapter waits as long as
  Google asks, then retries.
- **Model answers vary between runs.** The number check guarantees the figures are right, not that
  the wording is the same each time. `make assistant-eval` measures quality across fixed questions.
- **Only what the approved queries cover.** Forecasts, and anything outside sales, customers,
  receivables, suppliers and stock, get "not available" rather than a guess.
- **Free-tier data use.** Google may use free-tier requests to improve its products. That's why
  only fictional demo data is used (see [`docs/free-tier-limits.md`](../docs/free-tier-limits.md)).

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `AI_PROVIDER is blank` / `AI_MODEL is blank` / `AI_API_KEY is blank` | Fill them in `.env` (see Set it up). |
| `model API error HTTP 404 ... no longer available` | Google retired that model. Pick a current one in AI Studio and update `AI_MODEL`. |
| `model API error HTTP 429` after retries | You've reached the free-tier limit. Wait a minute (or until the next day for daily limits). |
| `AI_READER_PASSWORD is blank` or `password authentication failed for user "ai_reader"` | Run `make env-secrets`, `make up`, then `make db-init`. |
| `relation "ai.kpi_summary" does not exist` | Run `make pipeline-run` (or `ARGS="--dbt-only"`) to build the `ai` views. |
| The answer is a table of results instead of a sentence | The number check failed twice (status `fallback`). The figures shown are straight from SQL. `ops.assistant_log` records which numbers failed. |
