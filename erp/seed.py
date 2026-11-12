"""Load the Bluefield demo dataset into ERPNext (`make erp-seed`). Safe to rerun.

Masters (UOMs, groups, customers, items...) are looked up by name. Each transaction carries a
DEMO-... reference in a standard field (customer PO number, supplier bill number, payment
reference...), so a rerun finds what already exists and creates only what is missing. If a run
stops partway, run it again and it carries on from where it stopped.

Usage:
    uv run python -m erp.seed              # seed everything
    uv run python -m erp.seed --dry-run    # show what would be created, no network
    uv run python -m erp.seed --until 2025-11-30   # stop after this date (for a quick trial)
"""

import argparse
import sys
from collections import Counter
from collections.abc import Callable
from datetime import date
from typing import Any, Protocol

from erp import seed_data as sd
from erp.client import ErpClient, ErpError
from shared.config import Settings
from shared.logging import get_logger, new_run_id

BANK_ACCOUNT = f"Operating Account - {sd.ABBR}"
BANK_PARENT = f"Bank Accounts - {sd.ABBR}"
RECEIVABLE = f"Debtors - {sd.ABBR}"
PAYABLE = f"Creditors - {sd.ABBR}"
OPENING_EQUITY = f"Opening Balance Equity - {sd.ABBR}"
OPENING_STOCK_ACCOUNT = f"Temporary Opening - {sd.ABBR}"
FISCAL_YEAR_2025 = "2025"
OPENING_STOCK_TIME = "00:00:00"
# Goods arrive in the morning and ship in the afternoon. Each stock document on a day gets its own
# minute, because ERPNext queues a stock revaluation job whenever an existing entry has the same or
# a later timestamp than the new one.
FIRST_POSTING_MINUTE = {"purchase_invoice": 8 * 60, "sales_invoice": 12 * 60}

# Where each kind of transaction keeps its DEMO-... key.
LOOKUP = {
    "opening_cash": ("Journal Entry", "cheque_no"),
    "purchase_order": ("Purchase Order", "order_confirmation_no"),
    "purchase_invoice": ("Purchase Invoice", "bill_no"),
    "supplier_payment": ("Payment Entry", "reference_no"),
    "sales_order": ("Sales Order", "po_no"),
    "sales_invoice": ("Sales Invoice", "po_no"),
    "customer_payment": ("Payment Entry", "reference_no"),
}


class Erp(Protocol):
    """The part of ErpClient the seeder uses (tests pass an in-memory fake)."""

    def get_list(self, doctype: str, fields=..., filters=...) -> list[dict[str, Any]]: ...
    def get_doc(self, doctype: str, name: str) -> dict[str, Any]: ...
    def insert(self, doc: dict[str, Any]) -> dict[str, Any]: ...
    def submit(self, doctype: str, name: str) -> dict[str, Any]: ...


def _d(day: date) -> str:
    return day.isoformat()


def payment_key(kind: str, key: str) -> str:
    return f"{key}-PAY" if kind in ("customer_payment", "supplier_payment") else key


def posting_times(steps: list[sd.Step]) -> dict[tuple[str, str], str]:
    """A distinct, increasing posting time for each stock document within its day."""
    times: dict[tuple[str, str], str] = {}
    used: Counter[tuple[date, str]] = Counter()
    for step in steps:
        if step.kind in FIRST_POSTING_MINUTE:
            minute = FIRST_POSTING_MINUTE[step.kind] + used[(step.day, step.kind)]
            used[(step.day, step.kind)] += 1
            times[(step.kind, step.key)] = f"{minute // 60:02d}:{minute % 60:02d}:00"
    return times


# ---------------------------------------------------------------- masters


def master_docs(data: sd.Dataset) -> list[dict[str, Any]]:
    """Every master record, parents before children. Each has a `name` that ERPNext will give it."""
    docs: list[dict[str, Any]] = []
    for uom in sd.NEW_UOMS:
        docs.append({"doctype": "UOM", "name": uom, "uom_name": uom, "must_be_whole_number": 1})
    docs.append(
        {
            "doctype": "Fiscal Year",
            "name": FISCAL_YEAR_2025,
            "year": FISCAL_YEAR_2025,
            "year_start_date": "2025-01-01",
            "year_end_date": "2025-12-31",
            "companies": [{"company": sd.COMPANY}],
        }
    )
    docs.append(
        {
            "doctype": "Account",
            "name": BANK_ACCOUNT,
            "account_name": "Operating Account",
            "parent_account": BANK_PARENT,
            "company": sd.COMPANY,
            "account_type": "Bank",
            "account_currency": "USD",
        }
    )
    for territory in sd.TERRITORIES:
        docs.append(
            {
                "doctype": "Territory",
                "name": territory,
                "territory_name": territory,
                "parent_territory": sd.TERRITORY_PARENT,
            }
        )
    for group in sd.CUSTOMERS:
        docs.append(
            {
                "doctype": "Customer Group",
                "name": group,
                "customer_group_name": group,
                "parent_customer_group": sd.CUSTOMER_GROUP_PARENT,
            }
        )
    for group in sd.ITEM_GROUPS:
        docs.append(
            {
                "doctype": "Item Group",
                "name": group,
                "item_group_name": group,
                "parent_item_group": sd.ITEM_GROUP_PARENT,
            }
        )
    for supplier in data.suppliers:
        docs.append(
            {
                "doctype": "Supplier",
                "name": supplier.name,
                "supplier_name": supplier.name,
                "supplier_group": supplier.group,
                "country": "United States",
                "supplier_details": sd.DEMO_NOTE,
            }
        )
    for customer in data.customers:
        docs.append(
            {
                "doctype": "Customer",
                "name": customer.name,
                "customer_name": customer.name,
                "customer_type": "Company",
                "customer_group": customer.group,
                "territory": customer.territory,
                "email_id": customer.email,
                "customer_details": sd.DEMO_NOTE,
            }
        )
    for item in data.items:
        docs.append(
            {
                "doctype": "Item",
                "name": item.code,
                "item_code": item.code,
                "item_name": item.name,
                "item_group": item.group,
                "stock_uom": item.uom,
                "is_stock_item": 1,
                "include_item_in_manufacturing": 0,
                "valuation_rate": item.cost,
                "standard_rate": item.price,
                "description": f"{item.name}. {sd.DEMO_NOTE}",
                "item_defaults": [
                    {
                        "company": sd.COMPANY,
                        "default_warehouse": sd.WAREHOUSE,
                        "default_supplier": item.supplier,
                    }
                ],
                "reorder_levels": [
                    {
                        "warehouse": sd.WAREHOUSE,
                        "warehouse_reorder_level": item.reorder_level,
                        "warehouse_reorder_qty": item.reorder_qty,
                        "material_request_type": "Purchase",
                    }
                ],
            }
        )
    return docs


# ---------------------------------------------------------------- transactions


def opening_stock_doc(data: sd.Dataset) -> dict[str, Any]:
    return {
        "doctype": "Stock Reconciliation",
        "company": sd.COMPANY,
        "purpose": "Opening Stock",
        "posting_date": _d(sd.START),
        "posting_time": OPENING_STOCK_TIME,
        "set_posting_time": 1,
        "expense_account": OPENING_STOCK_ACCOUNT,
        "items": [
            {
                "item_code": item.code,
                "warehouse": sd.WAREHOUSE,
                "qty": item.opening_qty,
                "valuation_rate": item.cost,
            }
            for item in data.items
        ],
    }


def opening_cash_doc(key: str) -> dict[str, Any]:
    return {
        "doctype": "Journal Entry",
        "voucher_type": "Opening Entry",
        "is_opening": "Yes",
        "company": sd.COMPANY,
        "posting_date": _d(sd.START),
        "cheque_no": key,
        "cheque_date": _d(sd.START),
        "user_remark": sd.DEMO_NOTE,
        "accounts": [
            {"account": BANK_ACCOUNT, "debit_in_account_currency": sd.OPENING_CASH},
            {"account": OPENING_EQUITY, "credit_in_account_currency": sd.OPENING_CASH},
        ],
    }


def purchase_order_doc(po: sd.PurchaseOrder) -> dict[str, Any]:
    return {
        "doctype": "Purchase Order",
        "company": sd.COMPANY,
        "supplier": po.supplier,
        "transaction_date": _d(po.order_date),
        "schedule_date": _d(po.receipt_date),
        "set_warehouse": sd.WAREHOUSE,
        "order_confirmation_no": po.key,
        "items": [
            {
                "item_code": line.item_code,
                "qty": line.qty,
                "rate": line.rate,
                "schedule_date": _d(po.receipt_date),
                "warehouse": sd.WAREHOUSE,
            }
            for line in po.lines
        ],
    }


def purchase_invoice_doc(
    po: sd.PurchaseOrder, order: dict[str, Any], posting_time: str
) -> dict[str, Any]:
    """Supplier bill that also receives the goods (update_stock), linked to the purchase order."""
    rows = {row["item_code"]: row["name"] for row in order["items"]}
    return {
        "doctype": "Purchase Invoice",
        "company": sd.COMPANY,
        "supplier": po.supplier,
        "posting_date": _d(po.receipt_date),
        "posting_time": posting_time,
        "set_posting_time": 1,
        "bill_no": po.key,
        "bill_date": _d(po.receipt_date),
        "due_date": _d(po.due_date),
        "update_stock": 1,
        "set_warehouse": sd.WAREHOUSE,
        "remarks": sd.DEMO_NOTE,
        "items": [
            {
                "item_code": line.item_code,
                "qty": line.qty,
                "rate": line.rate,
                "warehouse": sd.WAREHOUSE,
                "purchase_order": order["name"],
                "po_detail": rows[line.item_code],
            }
            for line in po.lines
        ],
    }


def sales_order_doc(so: sd.SalesOrder) -> dict[str, Any]:
    return {
        "doctype": "Sales Order",
        "company": sd.COMPANY,
        "customer": so.customer,
        "transaction_date": _d(so.order_date),
        "delivery_date": _d(so.delivery_date),
        "po_no": so.key,
        "po_date": _d(so.order_date),
        "set_warehouse": sd.WAREHOUSE,
        "items": [
            {
                "item_code": line.item_code,
                "qty": line.qty,
                "rate": line.rate,
                "delivery_date": _d(so.delivery_date),
                "warehouse": sd.WAREHOUSE,
            }
            for line in so.lines
        ],
    }


def sales_invoice_doc(
    so: sd.SalesOrder, order: dict[str, Any], posting_time: str
) -> dict[str, Any]:
    """Invoice that also ships the goods (update_stock), linked to the sales order."""
    rows = {row["item_code"]: row["name"] for row in order["items"]}
    return {
        "doctype": "Sales Invoice",
        "company": sd.COMPANY,
        "customer": so.customer,
        "posting_date": _d(so.invoice_date),
        "posting_time": posting_time,
        "set_posting_time": 1,
        "due_date": _d(so.due_date),
        "po_no": so.key,
        "update_stock": 1,
        "set_warehouse": sd.WAREHOUSE,
        "remarks": sd.DEMO_NOTE,
        "items": [
            {
                "item_code": line.item_code,
                "qty": line.qty,
                "rate": line.rate,
                "warehouse": sd.WAREHOUSE,
                "sales_order": order["name"],
                "so_detail": rows[line.item_code],
            }
            for line in so.lines
        ],
    }


def payment_doc(
    kind: str, key: str, party: str, day: date, invoice: dict[str, Any], mode: str
) -> dict[str, Any]:
    """Payment Entry that settles one invoice in full."""
    amount = invoice.get("rounded_total") or invoice["grand_total"]
    receive = kind == "customer_payment"
    return {
        "doctype": "Payment Entry",
        "payment_type": "Receive" if receive else "Pay",
        "company": sd.COMPANY,
        "posting_date": _d(day),
        "party_type": "Customer" if receive else "Supplier",
        "party": party,
        "paid_from": RECEIVABLE if receive else BANK_ACCOUNT,
        "paid_to": BANK_ACCOUNT if receive else PAYABLE,
        "paid_amount": amount,
        "received_amount": amount,
        "reference_no": payment_key(kind, key),
        "reference_date": _d(day),
        "mode_of_payment": mode,
        "remarks": sd.DEMO_NOTE,
        "references": [
            {
                "reference_doctype": "Sales Invoice" if receive else "Purchase Invoice",
                "reference_name": invoice["name"],
                "allocated_amount": amount,
            }
        ],
    }


# ---------------------------------------------------------------- runner


class Seeder:
    def __init__(self, erp: Erp, data: sd.Dataset, log=None):
        self.erp = erp
        self.data = data
        self.log = log
        self.counts: Counter[str] = Counter()
        self.sales = {so.key: so for so in data.sales_orders}
        self.purchases = {po.key: po for po in data.purchase_orders}
        # kind -> {DEMO key -> existing record}, filled by _load_existing()
        self.existing: dict[str, dict[str, dict[str, Any]]] = {}
        self.times = posting_times(sd.build_steps(data))

    def _info(self, message: str, **fields: Any) -> None:
        if self.log:
            self.log.info(message, extra=fields)

    def seed_masters(self) -> None:
        names: dict[str, set[str]] = {}
        for doc in master_docs(self.data):
            doctype = doc["doctype"]
            if doctype not in names:
                names[doctype] = {row["name"] for row in self.erp.get_list(doctype)}
            if doc["name"] in names[doctype]:
                self.counts[f"{doctype}: kept"] += 1
                continue
            payload = {k: v for k, v in doc.items() if k != "name"}
            created = self.erp.insert(payload)
            names[doctype].add(created["name"])
            self.counts[f"{doctype}: created"] += 1
        self._info("Masters ready", counts=dict(self.counts))

    def _load_existing(self) -> None:
        """Index drafts and submitted documents by DEMO key (cancelled ones are ignored)."""
        live = ["docstatus", "in", [0, 1]]
        for kind, (doctype, field) in LOOKUP.items():
            fields = ["name", "docstatus", field]
            if doctype in ("Sales Invoice", "Purchase Invoice"):
                fields += ["grand_total", "rounded_total"]
            rows = self.erp.get_list(
                doctype, fields=fields, filters=[[field, "like", f"{sd.KEY_PREFIX}-%"], live]
            )
            self.existing.setdefault(kind, {})
            for row in rows:
                self.existing[kind][row[field]] = row
        stock = self.erp.get_list(
            "Stock Reconciliation",
            fields=["name", "docstatus"],
            filters=[["purpose", "=", "Opening Stock"], ["company", "=", sd.COMPANY], live],
        )
        self.existing["opening_stock"] = (
            {f"{sd.KEY_PREFIX}-OPENING-STOCK": stock[0]} if stock else {}
        )

    @staticmethod
    def _doctype(kind: str) -> str:
        return "Stock Reconciliation" if kind == "opening_stock" else LOOKUP[kind][0]

    def _order(self, kind: str, key: str) -> dict[str, Any]:
        """The submitted order (with item rows) that an invoice links to."""
        doctype = LOOKUP[kind][0]
        row = self.existing[kind][key]
        if "items" not in row:
            row = self.erp.get_doc(doctype, row["name"])
            self.existing[kind][key] = row
        return row

    def _build(self, step: sd.Step) -> dict[str, Any]:
        kind, key = step.kind, step.key
        if kind == "opening_stock":
            return opening_stock_doc(self.data)
        if kind == "opening_cash":
            return opening_cash_doc(key)
        if kind == "purchase_order":
            return purchase_order_doc(self.purchases[key])
        if kind == "purchase_invoice":
            order = self._order("purchase_order", key)
            return purchase_invoice_doc(self.purchases[key], order, self.times[(kind, key)])
        if kind == "sales_order":
            return sales_order_doc(self.sales[key])
        if kind == "sales_invoice":
            order = self._order("sales_order", key)
            return sales_invoice_doc(self.sales[key], order, self.times[(kind, key)])
        if kind == "customer_payment":
            so = self.sales[key]
            invoice = self.existing["sales_invoice"][key]
            return payment_doc(kind, key, so.customer, so.payment_date, invoice, so.mode_of_payment)
        if kind == "supplier_payment":
            po = self.purchases[key]
            invoice = self.existing["purchase_invoice"][key]
            return payment_doc(kind, key, po.supplier, po.payment_date, invoice, "Wire Transfer")
        raise ValueError(f"unknown step kind {kind}")

    def seed_transactions(self, until: date | None = None, progress_every: int = 100) -> None:
        self._load_existing()
        steps = [s for s in sd.build_steps(self.data) if until is None or s.day <= until]
        created = 0
        for step in steps:
            lookup_key = payment_key(step.kind, step.key)
            found = self.existing[step.kind].get(lookup_key)
            if found and found["docstatus"] == 1:
                self.counts[f"{step.kind}: kept"] += 1
                continue
            try:
                if found:  # a draft left by a run that stopped between save and submit
                    doctype = self._doctype(step.kind)
                    saved = self.erp.submit(doctype, found["name"])
                    self.counts[f"{step.kind}: draft submitted"] += 1
                else:
                    draft = self.erp.insert(self._build(step))
                    saved = self.erp.submit(draft["doctype"], draft["name"])
                    self.counts[f"{step.kind}: created"] += 1
            except ErpError as exc:
                raise SeedError(step, exc) from exc
            self.existing[step.kind][lookup_key] = saved
            created += 1
            if created % progress_every == 0:
                self._info(
                    "Progress", docs_created=created, total_steps=len(steps), day=_d(step.day)
                )
        self._info("Transactions done", docs_created=created, total_steps=len(steps))


class SeedError(Exception):
    def __init__(self, step: sd.Step, cause: ErpError):
        super().__init__(f"{step.kind} {step.key} ({step.day}): {cause}")
        self.step = step
        self.cause = cause


def plan_summary(data: sd.Dataset, until: date | None = None) -> dict[str, int]:
    steps = [s for s in sd.build_steps(data) if until is None or s.day <= until]
    summary = {
        f"masters: {k}": v for k, v in Counter(d["doctype"] for d in master_docs(data)).items()
    }
    summary.update({f"steps: {k}": v for k, v in Counter(s.kind for s in steps).items()})
    return summary


def main(
    argv: list[str] | None = None, make_client: Callable[[Settings], Erp] | None = None
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="show the plan; no network")
    parser.add_argument(
        "--until", type=date.fromisoformat, help="only seed steps on or before this date"
    )
    args = parser.parse_args(argv)

    settings = Settings()
    log = get_logger("erp.seed", new_run_id(), settings.log_level)
    data = sd.build_dataset()
    if args.dry_run:
        log.info("Dry run: nothing sent to ERPNext", extra={"plan": plan_summary(data, args.until)})
        return 0
    if make_client is None:
        if not (settings.erpnext_api_key and settings.erpnext_api_secret):
            log.error(
                "ERPNEXT_API_KEY or ERPNEXT_API_SECRET is blank in .env. Run `make erp-api-keys`."
            )
            return 1

        def make_client(s: Settings) -> Erp:
            return ErpClient(
                s.erpnext_url,
                s.erpnext_api_key.get_secret_value(),
                s.erpnext_api_secret.get_secret_value(),
            )

    erp = make_client(settings)
    seeder = Seeder(erp, data, log)
    log.info(
        "Seeding started",
        extra={"url": settings.erpnext_url, "until": args.until and _d(args.until)},
    )
    try:
        seeder.seed_masters()
        seeder.seed_transactions(until=args.until)
    except SeedError as exc:
        log.error(
            "ERPNext rejected a document. Fix the cause, then rerun; finished steps are kept.",
            extra={
                "step": exc.step.kind,
                "key": exc.step.key,
                "day": _d(exc.step.day),
                "error": str(exc.cause),
            },
        )
        return 1
    except ErpError as exc:
        log.error("ERPNext request failed", extra={"error": str(exc)})
        return 1
    finally:
        if hasattr(erp, "close"):
            erp.close()
    log.info("Seeding finished", extra={"counts": dict(sorted(seeder.counts.items()))})
    return 0


if __name__ == "__main__":
    sys.exit(main())
