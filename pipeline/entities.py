"""The ERPNext doctypes the pipeline copies, and the raw table each one lands in."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Entity:
    doctype: str
    table: str  # table name in the raw schema
    parent: str | None = None  # set for child tables (invoice lines and similar)


ENTITIES: tuple[Entity, ...] = (
    Entity("Customer Group", "erpnext_customer_group"),
    Entity("Territory", "erpnext_territory"),
    Entity("Item Group", "erpnext_item_group"),
    Entity("Customer", "erpnext_customer"),
    Entity("Supplier", "erpnext_supplier"),
    Entity("Item", "erpnext_item"),
    Entity("Item Reorder", "erpnext_item_reorder", parent="Item"),
    Entity("Item Default", "erpnext_item_default", parent="Item"),
    Entity("Bin", "erpnext_bin"),
    Entity("Sales Order", "erpnext_sales_order"),
    Entity("Sales Order Item", "erpnext_sales_order_item", parent="Sales Order"),
    Entity("Sales Invoice", "erpnext_sales_invoice"),
    Entity("Sales Invoice Item", "erpnext_sales_invoice_item", parent="Sales Invoice"),
    Entity("Purchase Order", "erpnext_purchase_order"),
    Entity("Purchase Order Item", "erpnext_purchase_order_item", parent="Purchase Order"),
    Entity("Purchase Invoice", "erpnext_purchase_invoice"),
    Entity("Purchase Invoice Item", "erpnext_purchase_invoice_item", parent="Purchase Invoice"),
    Entity("Payment Entry", "erpnext_payment_entry"),
    Entity("Payment Entry Reference", "erpnext_payment_entry_reference", parent="Payment Entry"),
)

PARENTS: tuple[Entity, ...] = tuple(e for e in ENTITIES if e.parent is None)


def children_of(doctype: str) -> tuple[Entity, ...]:
    return tuple(e for e in ENTITIES if e.parent == doctype)
