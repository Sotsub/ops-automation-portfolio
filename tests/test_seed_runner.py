"""The seeder against an in-memory fake ERPNext: right documents, right order, safe to rerun."""

import itertools
from datetime import date

import pytest

from erp import seed
from erp import seed_data as sd
from erp.client import ErpError

TRIAL_END = date(2025, 11, 30)


class FakeErp:
    """Stores documents in memory and answers the few calls the seeder makes."""

    def __init__(self, fail_on: tuple[str, str] | None = None, fail_submit: str | None = None):
        self.docs: dict[str, dict[str, dict]] = {}
        self.calls: list[tuple[str, str]] = []
        self._ids = itertools.count(1)
        self.fail_on = fail_on  # (doctype, DEMO key) whose insert is rejected
        self.fail_submit = fail_submit  # doctype whose submit is rejected (leaves a draft)

    def get_list(self, doctype, fields=("name",), filters=None):
        self.calls.append(("list", doctype))
        rows = []
        for doc in self.docs.get(doctype, {}).values():
            if all(self._match(doc, f) for f in filters or []):
                rows.append({f: doc.get(f) for f in fields})
        return rows

    @staticmethod
    def _match(doc, flt):
        field, op, value = flt
        if op == "=":
            return doc.get(field) == value
        if op == "in":
            return doc.get(field) in value
        if op == "like":
            return str(doc.get(field, "")).startswith(value.rstrip("%"))
        raise AssertionError(op)

    def get_doc(self, doctype, name):
        self.calls.append(("get", doctype))
        return dict(self.docs[doctype][name])

    def insert(self, doc):
        self.calls.append(("insert", doc["doctype"]))
        assert "docstatus" not in doc, "transactions are saved as drafts, then submitted"
        if self.fail_on and doc["doctype"] == self.fail_on[0] and self.fail_on[1] in str(doc):
            raise ErpError(417, "Simulated validation failure", "ValidationError")
        name = doc.get("name") or self._name(doc)
        saved = {**doc, "name": name, "docstatus": 0}
        for i, row in enumerate(saved.get("items", [])):
            saved["items"][i] = {**row, "name": f"{name}-row{i}"}
        if doc["doctype"] in ("Sales Invoice", "Purchase Invoice"):
            saved["grand_total"] = round(sum(r["qty"] * r["rate"] for r in doc["items"]), 2)
            saved["rounded_total"] = round(saved["grand_total"])
        self.docs.setdefault(doc["doctype"], {})[name] = saved
        return dict(saved)

    def submit(self, doctype, name):
        self.calls.append(("submit", doctype))
        if self.fail_submit == doctype:
            raise ErpError(417, "Simulated submit failure", "ValidationError")
        self.docs[doctype][name]["docstatus"] = 1
        return dict(self.docs[doctype][name])

    def _name(self, doc):
        for field in ("item_code", "customer_name", "supplier_name", "uom_name", "year"):
            if field in doc:
                return doc[field]
        if doc["doctype"] == "Account":
            return f"{doc['account_name']} - {sd.ABBR}"
        for field in ("territory_name", "customer_group_name", "item_group_name"):
            if field in doc:
                return doc[field]
        return f"{doc['doctype']}-{next(self._ids):05d}"

    def count(self, doctype, docstatus=1):
        return sum(1 for d in self.docs.get(doctype, {}).values() if d["docstatus"] == docstatus)


@pytest.fixture(scope="module")
def data():
    return sd.build_dataset()


def run(erp, data, until=TRIAL_END):
    seeder = seed.Seeder(erp, data)
    seeder.seed_masters()
    seeder.seed_transactions(until=until)
    return seeder.counts


def test_trial_month_creates_expected_documents(data):
    erp = FakeErp()
    run(erp, data)
    november = [s for s in sd.build_steps(data) if s.day <= TRIAL_END]
    expected = {kind: sum(1 for s in november if s.kind == kind) for kind in seed.LOOKUP}
    assert erp.count("Sales Order") == expected["sales_order"] > 0
    assert erp.count("Sales Invoice") == expected["sales_invoice"] > 0
    assert erp.count("Purchase Order") == expected["purchase_order"] > 0
    assert erp.count("Stock Reconciliation") == 1
    assert erp.count("Journal Entry") == 1
    assert len(erp.docs["Customer"]) == 40 and len(erp.docs["Item"]) == 45


def test_rerun_creates_nothing_new(data):
    erp = FakeErp()
    run(erp, data)
    before = {doctype: dict(docs) for doctype, docs in erp.docs.items()}
    counts = run(erp, data)
    assert erp.docs == before
    assert not any(key.endswith(": created") for key in counts), counts


def test_stopped_run_resumes_without_duplicates(data):
    first = data.sales_orders[5].key
    erp = FakeErp(fail_on=("Sales Order", first))
    with pytest.raises(seed.SeedError) as err:
        run(erp, data)
    assert err.value.step.key == first
    erp.fail_on = None
    run(erp, data)
    keys = [d["po_no"] for d in erp.docs["Sales Order"].values()]
    assert len(keys) == len(set(keys)), "a resumed run must not duplicate orders"
    assert first in keys


def test_draft_left_by_failed_submit_is_submitted_on_rerun(data):
    erp = FakeErp(fail_submit="Purchase Order")
    with pytest.raises(seed.SeedError):
        run(erp, data)
    assert erp.count("Purchase Order", docstatus=0) == 1
    erp.fail_submit = None
    counts = run(erp, data)
    assert counts["purchase_order: draft submitted"] == 1
    assert erp.count("Purchase Order", docstatus=0) == 0
    keys = [d["order_confirmation_no"] for d in erp.docs["Purchase Order"].values()]
    assert len(keys) == len(set(keys))


def test_invoices_link_to_their_orders_and_payments_settle_them(data):
    erp = FakeErp()
    run(erp, data)
    orders = {d["po_no"]: d for d in erp.docs["Sales Order"].values()}
    invoices = {d["po_no"]: d for d in erp.docs["Sales Invoice"].values()}
    for key, invoice in invoices.items():
        rows = {r["name"] for r in orders[key]["items"]}
        assert all(item["sales_order"] == orders[key]["name"] for item in invoice["items"])
        assert {item["so_detail"] for item in invoice["items"]} <= rows
        assert invoice["update_stock"] == 1
    for payment in erp.docs.get("Payment Entry", {}).values():
        ref = payment["references"][0]
        invoice = erp.docs[ref["reference_doctype"]][ref["reference_name"]]
        assert payment["paid_amount"] == ref["allocated_amount"] == invoice["rounded_total"]


def test_same_day_stock_documents_get_distinct_increasing_times(data):
    steps = sd.build_steps(data)
    times = seed.posting_times(steps)
    by_day: dict[tuple[date, str], list[str]] = {}
    for step in steps:
        if (step.kind, step.key) in times:
            by_day.setdefault((step.day, step.kind), []).append(times[(step.kind, step.key)])
    for (day, kind), values in by_day.items():
        assert values == sorted(values) and len(values) == len(set(values)), (day, kind)
    assert all(t < "12:00:00" for (k, _), t in times.items() if k == "purchase_invoice")
    assert all(t >= "12:00:00" for (k, _), t in times.items() if k == "sales_invoice")


def test_every_master_and_transaction_is_labelled_demo(data):
    erp = FakeErp()
    run(erp, data)
    for doc in erp.docs["Customer"].values():
        assert doc["customer_details"] == sd.DEMO_NOTE and doc["email_id"].endswith(".example.com")
    for doc in erp.docs["Item"].values():
        assert sd.DEMO_NOTE in doc["description"]
    for doctype in ("Sales Invoice", "Purchase Invoice", "Payment Entry"):
        assert all(d["remarks"] == sd.DEMO_NOTE for d in erp.docs[doctype].values())


def test_dry_run_needs_no_erpnext_or_keys(monkeypatch):
    monkeypatch.delenv("ERPNEXT_API_KEY", raising=False)

    def no_client(_settings):
        raise AssertionError("dry run must not connect")

    assert seed.main(["--dry-run"], make_client=no_client) == 0


def test_main_reports_rejected_document_and_fails(data, monkeypatch):
    erp = FakeErp(fail_on=("Sales Order", data.sales_orders[0].key))
    assert seed.main(["--until", TRIAL_END.isoformat()], make_client=lambda _s: erp) == 1
