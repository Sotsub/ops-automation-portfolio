"""The demo dataset is deterministic, fictional, and internally consistent. No ERPNext needed."""

from collections import Counter

import pytest

from erp import seed_data as sd


@pytest.fixture(scope="module")
def data() -> sd.Dataset:
    return sd.build_dataset()


@pytest.fixture(scope="module")
def steps(data) -> list[sd.Step]:
    return sd.build_steps(data)


def test_same_seed_gives_identical_data(data):
    assert sd.build_dataset() == data


def test_different_seed_gives_different_data(data):
    assert sd.build_dataset(seed=sd.SEED + 1).sales_orders != data.sales_orders


def test_volume_is_a_year_of_small_distributor_trade(data):
    assert len(data.items) == len(sd.CATALOG) == 45
    assert len(data.customers) == 40
    assert len(data.suppliers) == 12
    assert 500 <= len(data.sales_orders) <= 750
    assert 150 <= len(data.purchase_orders) <= 400


def test_every_transaction_falls_inside_the_trading_year(data):
    for so in data.sales_orders:
        assert sd.START <= so.order_date <= sd.END
        assert sd.is_weekday(so.order_date)
        assert so.invoice_date is None or so.order_date < so.invoice_date <= sd.END
        assert so.payment_date is None or so.invoice_date < so.payment_date <= sd.END
    for po in data.purchase_orders:
        assert sd.START <= po.order_date <= sd.END
        assert po.order_date < po.receipt_date
        assert po.payment_date is None or (
            po.received and po.receipt_date < po.payment_date <= sd.END
        )


def test_stock_never_goes_negative_when_replayed_in_step_order(data, steps):
    """Replay the steps the way ERPNext will post them and check stock at every point."""
    stock = {item.code: 0 for item in data.items}
    sales = {so.key: so for so in data.sales_orders}
    purchases = {po.key: po for po in data.purchase_orders}
    for step in steps:
        if step.kind == "opening_stock":
            for item in data.items:
                stock[item.code] += item.opening_qty
        elif step.kind == "purchase_invoice":
            for line in purchases[step.key].lines:
                stock[line.item_code] += line.qty
        elif step.kind == "sales_invoice":
            for line in sales[step.key].lines:
                stock[line.item_code] -= line.qty
                assert stock[line.item_code] >= 0, f"{step.key} oversells {line.item_code}"
    # Uninvoiced orders were reserved in the simulation but haven't shipped yet.
    reserved = Counter()
    for so in data.sales_orders:
        if so.invoice_date is None:
            for line in so.lines:
                reserved[line.item_code] += line.qty
    assert {code: qty - reserved[code] for code, qty in stock.items()} == data.closing_stock


def test_steps_are_chronological_and_dependencies_come_first(steps):
    days = [s.day for s in steps]
    assert days == sorted(days)
    seen = set()
    needs = {
        "sales_invoice": "sales_order",
        "customer_payment": "sales_invoice",
        "purchase_invoice": "purchase_order",
        "supplier_payment": "purchase_invoice",
    }
    for step in steps:
        if step.kind in needs:
            assert (needs[step.kind], step.key) in seen, f"{step.kind} {step.key} before its parent"
        seen.add((step.kind, step.key))
    assert steps[0].kind == "opening_stock"


def test_keys_are_unique_and_marked_demo(data):
    keys = [so.key for so in data.sales_orders] + [po.key for po in data.purchase_orders]
    assert len(keys) == len(set(keys))
    assert all(key.startswith(f"{sd.KEY_PREFIX}-") for key in keys)


def test_contacts_are_fictional(data):
    for customer in data.customers:
        assert customer.email.endswith(".example.com"), customer.email
    assert len({c.name for c in data.customers}) == len(data.customers)


def test_items_have_sane_prices_and_reorder_settings(data):
    for item in data.items:
        assert item.price > item.cost > 0
        assert item.reorder_qty > item.reorder_level > 0
        assert item.opening_qty == item.reorder_level + item.reorder_qty
        assert item.supplier in {s.name for s in data.suppliers}
        assert item.uom in sd.NEW_UOMS + ("Box",)


def test_reports_will_have_something_to_find(data):
    """Later projects need overdue invoices, open orders, and low stock to report on."""
    unpaid = [so for so in data.sales_orders if so.invoice_date and not so.payment_date]
    paid_late = [
        so for so in data.sales_orders if so.payment_date and so.payment_date > so.due_date
    ]
    assert len(unpaid) >= 10
    assert len(paid_late) >= 50
    assert any(not po.received for po in data.purchase_orders)
    low = [i for i in data.items if data.closing_stock[i.code] <= i.reorder_level]
    assert set(sd.BACKORDERED_ITEMS) <= {i.code for i in low}


def test_price_increase_applies_from_its_date(data):
    item = data.item("BSC-CHM-001")
    before = [
        line.rate / (1 - c.discount)
        for so in data.sales_orders
        if so.order_date < sd.PRICE_INCREASE_DATE
        for c in data.customers
        if c.name == so.customer
        for line in so.lines
        if line.item_code == item.code
    ]
    assert before and all(rate == pytest.approx(item.price, abs=0.02) for rate in before)


def test_add_business_days_skips_weekends():
    from datetime import date

    friday = date(2026, 1, 2)
    assert sd.add_business_days(friday, 1) == date(2026, 1, 5)
    assert sd.add_business_days(friday, 5) == date(2026, 1, 9)
