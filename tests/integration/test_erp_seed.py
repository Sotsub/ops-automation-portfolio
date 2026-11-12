"""Live checks on the seeded ERPNext site (after erp-up, erp-api-keys and erp-seed).

Run with `make erp-seed-check`. The API key comes from .env and is never printed.
"""

from collections import Counter

import pytest

from erp import seed
from erp import seed_data as sd
from erp.client import ErpClient
from shared.config import Settings

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def erp():
    s = Settings()
    if not (s.erpnext_api_key and s.erpnext_api_secret):
        pytest.fail("ERPNEXT_API_KEY/SECRET missing from .env. Run `make erp-api-keys`.")
    with ErpClient(
        s.erpnext_url, s.erpnext_api_key.get_secret_value(), s.erpnext_api_secret.get_secret_value()
    ) as client:
        yield client


@pytest.fixture(scope="module")
def data():
    return sd.build_dataset()


def submitted(erp, doctype, fields=("name",)):
    return erp.get_list(doctype, fields=list(fields), filters=[["docstatus", "=", 1]])


def test_company_is_the_us_demo_company(erp):
    company = erp.get_doc("Company", sd.COMPANY)
    assert (company["country"], company["default_currency"]) == ("United States", "USD")


def test_every_planned_document_exists_exactly_once(erp, data):
    planned = Counter(step.kind for step in sd.build_steps(data))
    for kind, (doctype, field) in seed.LOOKUP.items():
        keys = [
            row[field]
            for row in submitted(erp, doctype, ["name", field])
            if (row[field] or "").startswith(f"{sd.KEY_PREFIX}-")
            and (
                kind not in ("customer_payment", "supplier_payment") or row[field].endswith("-PAY")
            )
            and (kind != "customer_payment" or "-SO-" in row[field])
            and (kind != "supplier_payment" or "-PO-" in row[field])
        ]
        assert len(keys) == len(set(keys)), f"duplicate {doctype}"
        assert len(keys) == planned[kind], (
            f"{kind}: {len(keys)} in ERPNext, {planned[kind]} planned"
        )


def test_masters_are_complete(erp, data):
    assert {r["name"] for r in erp.get_list("Customer")} >= {c.name for c in data.customers}
    assert {r["name"] for r in erp.get_list("Item")} >= {i.code for i in data.items}
    assert {r["name"] for r in erp.get_list("Supplier")} >= {s.name for s in data.suppliers}


def test_no_submitted_order_is_left_with_draft_status(erp):
    for doctype in ("Sales Order", "Purchase Order", "Sales Invoice", "Purchase Invoice"):
        statuses = Counter(r["status"] for r in submitted(erp, doctype, ["status"]))
        assert "Draft" not in statuses, f"{doctype}: {dict(statuses)}"


def test_open_and_overdue_work_exists_for_reports(erp):
    invoices = Counter(r["status"] for r in submitted(erp, "Sales Invoice", ["status"]))
    assert invoices["Paid"] > 400 and invoices["Overdue"] >= 10, dict(invoices)
    assert any(
        r["status"] == "To Receive and Bill" for r in submitted(erp, "Purchase Order", ["status"])
    )


def test_stock_matches_the_simulation_and_is_never_negative(erp, data):
    bins = {
        r["item_code"]: r["actual_qty"]
        for r in erp.get_list(
            "Bin", ["item_code", "actual_qty"], [["warehouse", "=", sd.WAREHOUSE]]
        )
    }
    reserved = Counter()
    for so in data.sales_orders:
        if so.invoice_date is None:
            for line in so.lines:
                reserved[line.item_code] += line.qty
    for item in data.items:
        assert bins[item.code] >= 0
        assert bins[item.code] == data.closing_stock[item.code] + reserved[item.code], item.code


def test_ledger_balances_and_no_revaluation_was_needed(erp):
    gl = erp.get_list("GL Entry", ["debit", "credit"], [["is_cancelled", "=", 0]])
    assert round(sum(g["debit"] - g["credit"] for g in gl), 2) == 0
    queued = erp.get_list("Repost Item Valuation", ["name"], [["status", "!=", "Completed"]])
    assert queued == [], "stock documents were posted out of order"


def test_rerun_creates_nothing(erp, data):
    seeder = seed.Seeder(erp, data)
    seeder.seed_masters()
    seeder.seed_transactions()
    created = {k: v for k, v in seeder.counts.items() if not k.endswith(": kept")}
    assert created == {}
