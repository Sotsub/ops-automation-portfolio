# Free-tier limits

This portfolio runs for $0. This page lists each free allowance it depends on, what in this repository
uses it, and how to stay inside it. Vendor limits change, so recheck the linked pages before relying on a number.

**Last checked: 2026-11-10.**

## Monthly allowances

| Service | Free allowance | What uses it here | How to stay inside it |
| --- | --- | --- | --- |
| [GitHub Codespaces compute](https://docs.github.com/en/billing/concepts/product-billing/github-codespaces) | 120 core-hours per month on a personal GitHub Free account. That's about **60 hours on 2 cores** or **30 hours on 4 cores** | Every minute a Codespace is running, whether or not containers are busy | Use the 2-core machine. Start only the profiles you need (table below). Stop the Codespace when you finish |
| [GitHub Codespaces storage](https://docs.github.com/en/billing/concepts/product-billing/github-codespaces) | 15 GB-month | The Codespace disk, including Docker images and volumes. ERPNext's images and database are the largest. A **stopped** Codespace still uses storage | Keep one Codespace. Delete old ones. Run `docker image prune` after version upgrades |
| [Codespaces idle timeout](https://docs.github.com/en/codespaces/setting-your-user-preferences/setting-your-timeout-period-for-github-codespaces) | Stops an idle Codespace after 30 minutes by default (you can set 5–240) | Protects compute hours if you forget to stop it | Keep it at 30 minutes or lower in GitHub → Settings → Codespaces |
| [Codespaces retention](https://docs.github.com/en/codespaces/setting-your-user-preferences/configuring-automatic-deletion-of-your-codespaces) | Codespaces stopped and inactive for 30 days are deleted automatically, **even with unpushed changes** | Your working copy, `.env`, and Docker data | Commit and push work. The demo data is rebuilt by script, so losing volumes costs time but not data |
| [GitHub Actions](https://docs.github.com/en/billing/concepts/product-billing/github-actions) | Free for standard GitHub-hosted runners in **public** repositories | `.github/workflows/ci.yml`: lint and unit tests on every push | Keep the repository public. CI never starts Docker or calls AI |
| [Gemini API free tier](https://aistudio.google.com/docs/billing) | Some models, up to their [free-tier rate limits](https://aistudio.google.com/rate-limit). No billing account is needed | The AI client from the next milestone, then Projects 2, 4, 5, and 6 | Batch evaluation runs over several days, honor Retry-After, and cache responses while testing |
| Slack free workspace | Free plan | Alerts and the assistant demos (Projects 1–4, 6) | Use a separate demo workspace |
| Shopify development store | Free for development, test data only | Project 3 sync | Never use real customer data |
| Cloudflare Quick Tunnel | Free temporary URL | Exposing only the Shopify webhook endpoint during Project 3 demos | Close it after the demo |

**No payment method on GitHub or Google.** On GitHub, usage beyond the included quota is blocked rather than
billed when there's no payment method. You can't create or resume Codespaces until the next cycle, but
you can still export unsaved changes to a branch. Check the billing pages once a month.

**AI data rule.** Google's billing page says only *paid* use can be kept out of product improvement. Treat
everything sent to a free tier as possibly used by the provider: **fictional demo data only**, never client
or personal data.

## What each make target costs

Everything below runs inside the Codespace, so it all draws on the same compute hours. Memory is what
decides the machine size.

| Command | Starts | Typical use | Machine |
| --- | --- | --- | --- |
| `make test` / `make lint` | Nothing | Everyday coding against saved fixtures | 2-core |
| `make up` | Core: Postgres, Mailpit | Pipeline and SQL work | 2-core |
| `make up-reporting` | Core + Metabase | Building dashboards | 2-core |
| `make up-automation` | Core + n8n | Building workflows | 2-core |
| `make erp-up` | ERPNext (separate project) | Seeding, extract development, demos | 2-core on its own |
| `make ask Q="..."` | Nothing (needs Postgres up) | One assistant question: about 2-4 Gemini free-tier requests | 2-core |
| `make assistant-eval` | Nothing (needs Postgres up) | 14 test questions: about 35 Gemini requests over 5 minutes. Run it after changing the assistant, not on every commit | 2-core |
| `make up-all` + `make erp-up` | Everything | Full end-to-end demo or video recording | **4-core** (uses hours twice as fast) |

Stop what you aren't using: `make stop-reporting`, `make stop-automation`, `make down` (whole stack),
`make erp-down`. Then stop the Codespace.

## Limits this places on claims

A Codespace isn't always on, so n8n schedules run only while it's running. The README describes this
as a portfolio deployment. It shows that schedules are configured and runs them during demos,
and doesn't claim 24/7 operation.
