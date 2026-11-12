"""Deterministic demo data for Bluefield Supply Co., a fictional distributor.

Pure Python: no network and no ERPNext. `build_dataset()` simulates a year of trading day by day
(orders arrive, stock goes out, low items are reordered from suppliers) and always returns the same
records for the same SEED. Stock never goes negative, because an order only takes what is on hand.

Everything here is invented. Names, emails (example.com), prices and quantities are demo values.
"""

import math
import random
from dataclasses import dataclass
from datetime import date, timedelta

SEED = 20251101
START = date(2025, 11, 1)  # Opening stock and cash are posted on this date.
END = date(
    2026, 10, 31
)  # Last day of simulated trading. Later steps (payments, receipts) stay open.
COMPANY = "Bluefield Supply Co."
ABBR = "BSC"
WAREHOUSE = f"Stores - {ABBR}"
DEMO_NOTE = (
    "Fictional demo data for Bluefield Supply Co. (portfolio demo, not a real business record)."
)
KEY_PREFIX = "DEMO"  # Every seeded transaction carries a DEMO-... reference so reruns can find it.

OPENING_CASH = 150_000.00
PRICE_INCREASE_DATE = date(2026, 3, 1)  # Annual list-price increase.
PRICE_INCREASE = 0.04
NET_DAYS = 30
ORDERS_PER_WEEKDAY = 2.4
# Quieter over the holidays, busier in late summer when schools and offices restock.
SEASONALITY = {
    1: 0.85, 2: 0.9, 3: 1.0, 4: 1.0, 5: 1.05, 6: 1.0,
    7: 1.05, 8: 1.25, 9: 1.2, 10: 1.05, 11: 0.95, 12: 0.8,
}  # fmt: skip
LINES_PER_ORDER = {1: 25, 2: 30, 3: 25, 4: 13, 5: 7}  # count: weight
QTY_SCALE = 3  # multiplies each catalog item's typical order quantity
REORDER_WEEKDAYS = (0, 3)  # purchasing reviews stock on Mondays and Thursdays
# Items whose supplier is backordered from this date, so they end the year below reorder level.
BACKORDER_FROM = date(2026, 9, 15)
BACKORDERED_ITEMS = ("BSC-PPE-002", "BSC-PAP-003", "BSC-CHM-005")

TERRITORY_PARENT = "United States"
TERRITORIES = ("Northeast", "Southeast", "Midwest", "Southwest", "West")
CUSTOMER_GROUP_PARENT = "All Customer Groups"
ITEM_GROUP_PARENT = "All Item Groups"
NEW_UOMS = ("Case", "Pack", "Each")
MODES_OF_PAYMENT = {"Wire Transfer": 45, "Check": 35, "Credit Card": 20}
# How many days after the invoice each kind of customer pays.
PAY_PROFILES = {
    "prompt": ((7, 25), 35),
    "normal": ((22, 40), 40),
    "late": ((38, 75), 18),
    "slow": ((55, 130), 7),
}

# item group -> code prefix
ITEM_GROUPS = {
    "Cleaning Chemicals": "CHM",
    "Paper Products": "PAP",
    "Liners & Packaging": "PKG",
    "Safety & PPE": "PPE",
    "Janitorial Equipment": "EQP",
}

# name, supplier group, lead time in business days
SUPPLIERS = (
    ("Clearwater Chemical Supply", "Distributor", 5),
    ("Ridgeline Janitorial Wholesale", "Distributor", 4),
    ("Northfield Paper Mills", "Local", 7),
    ("Great Lakes Tissue Co.", "Distributor", 6),
    ("Keystone Poly Bags", "Local", 8),
    ("Pinecrest Packaging", "Local", 5),
    ("Ironclad Safety Products", "Hardware", 6),
    ("Brightline PPE Supply", "Distributor", 4),
    ("Summitview Tool & Equipment", "Hardware", 9),
    ("Bayside Industrial Supply", "Local", 3),
    ("Copperleaf Distribution", "Distributor", 6),
    ("Prairie Wind Manufacturing", "Hardware", 10),
)

# group, item name, stock UOM, unit cost (USD), markup, popularity, typical qty per order line, supplier
CATALOG = (
    ("Cleaning Chemicals", "All-Purpose Cleaner, 1 gal", "Each", 6.20, 1.65, 9, 8, "Clearwater Chemical Supply"),
    ("Cleaning Chemicals", "All-Purpose Cleaner, case of 4 x 1 gal", "Case", 23.00, 1.55, 7, 3, "Clearwater Chemical Supply"),
    ("Cleaning Chemicals", "Glass Cleaner, 1 gal", "Each", 5.40, 1.70, 6, 6, "Clearwater Chemical Supply"),
    ("Cleaning Chemicals", "Neutral Floor Cleaner, case of 4 x 1 gal", "Case", 27.50, 1.50, 6, 2, "Ridgeline Janitorial Wholesale"),
    ("Cleaning Chemicals", "Heavy-Duty Degreaser, 1 gal", "Each", 9.80, 1.60, 4, 4, "Ridgeline Janitorial Wholesale"),
    ("Cleaning Chemicals", "Disinfectant Spray, case of 12 x 32 oz", "Case", 34.00, 1.55, 8, 2, "Clearwater Chemical Supply"),
    ("Cleaning Chemicals", "Foaming Hand Soap Refill, case of 4", "Case", 31.00, 1.60, 7, 3, "Copperleaf Distribution"),
    ("Cleaning Chemicals", "Hand Sanitizer Gel, case of 6 x 1 L", "Case", 38.50, 1.55, 6, 2, "Copperleaf Distribution"),
    ("Cleaning Chemicals", "Restroom Cleaner, case of 12 x 32 oz", "Case", 29.00, 1.60, 5, 2, "Ridgeline Janitorial Wholesale"),
    ("Cleaning Chemicals", "Carpet Spot Remover, case of 12", "Case", 41.00, 1.50, 2, 1, "Ridgeline Janitorial Wholesale"),
    ("Paper Products", "Multifold Paper Towels, case of 16 packs", "Case", 24.00, 1.45, 10, 5, "Northfield Paper Mills"),
    ("Paper Products", "Hardwound Roll Towels, case of 6", "Case", 32.00, 1.45, 7, 4, "Northfield Paper Mills"),
    ("Paper Products", "Toilet Tissue 2-Ply, case of 96 rolls", "Case", 46.00, 1.40, 10, 4, "Great Lakes Tissue Co."),
    ("Paper Products", "Jumbo Roll Toilet Tissue, case of 12", "Case", 39.00, 1.45, 6, 3, "Great Lakes Tissue Co."),
    ("Paper Products", "Facial Tissue, case of 30 boxes", "Case", 28.00, 1.50, 5, 2, "Great Lakes Tissue Co."),
    ("Paper Products", "Kitchen Roll Towels, case of 30", "Case", 30.00, 1.45, 5, 2, "Northfield Paper Mills"),
    ("Paper Products", "Seat Covers, case of 20 packs", "Case", 22.00, 1.55, 3, 2, "Great Lakes Tissue Co."),
    ("Paper Products", "Dinner Napkins, case of 3000", "Case", 26.00, 1.50, 4, 2, "Northfield Paper Mills"),
    ("Liners & Packaging", "Trash Liners 33 gal, case of 250", "Case", 27.00, 1.50, 9, 4, "Keystone Poly Bags"),
    ("Liners & Packaging", "Heavy-Duty Liners 55 gal, case of 100", "Case", 36.00, 1.50, 6, 3, "Keystone Poly Bags"),
    ("Liners & Packaging", "Small Liners 10 gal, case of 500", "Case", 21.00, 1.55, 5, 2, "Keystone Poly Bags"),
    ("Liners & Packaging", "Stretch Wrap 18 in, case of 4 rolls", "Case", 44.00, 1.40, 4, 2, "Pinecrest Packaging"),
    ("Liners & Packaging", "Corrugated Boxes 12x12x12, bundle of 25", "Pack", 18.50, 1.60, 5, 3, "Pinecrest Packaging"),
    ("Liners & Packaging", "Packing Tape 2 in, case of 36 rolls", "Case", 33.00, 1.50, 5, 2, "Pinecrest Packaging"),
    ("Liners & Packaging", "Bubble Wrap 12 in x 175 ft", "Each", 16.00, 1.65, 3, 2, "Pinecrest Packaging"),
    ("Liners & Packaging", "Food Storage Bags, case of 500", "Case", 19.00, 1.55, 3, 2, "Keystone Poly Bags"),
    ("Safety & PPE", "Nitrile Gloves Medium, box of 100", "Box", 7.20, 1.70, 9, 10, "Brightline PPE Supply"),
    ("Safety & PPE", "Nitrile Gloves Large, box of 100", "Box", 7.20, 1.70, 9, 10, "Brightline PPE Supply"),
    ("Safety & PPE", "Nitrile Gloves X-Large, box of 100", "Box", 7.60, 1.70, 5, 6, "Brightline PPE Supply"),
    ("Safety & PPE", "Disposable Face Masks, box of 50", "Box", 6.00, 1.75, 6, 8, "Brightline PPE Supply"),
    ("Safety & PPE", "Safety Glasses, clear, pack of 12", "Pack", 18.00, 1.65, 4, 2, "Ironclad Safety Products"),
    ("Safety & PPE", "Hi-Vis Safety Vest, each", "Each", 5.50, 1.80, 3, 6, "Ironclad Safety Products"),
    ("Safety & PPE", "Foam Ear Plugs, box of 200", "Box", 15.00, 1.65, 3, 2, "Ironclad Safety Products"),
    ("Safety & PPE", "Shoe Covers, case of 300", "Case", 24.00, 1.60, 3, 2, "Brightline PPE Supply"),
    ("Safety & PPE", "First Aid Kit, 50-person", "Each", 29.00, 1.70, 2, 1, "Ironclad Safety Products"),
    ("Janitorial Equipment", "Wet Mop Head, large", "Each", 6.80, 1.80, 6, 6, "Ridgeline Janitorial Wholesale"),
    ("Janitorial Equipment", "Mop Bucket with Wringer, 35 qt", "Each", 58.00, 1.55, 2, 1, "Summitview Tool & Equipment"),
    ("Janitorial Equipment", "Microfiber Cloths, pack of 24", "Pack", 14.50, 1.75, 8, 3, "Bayside Industrial Supply"),
    ("Janitorial Equipment", "Angle Broom, each", "Each", 8.90, 1.75, 4, 3, "Summitview Tool & Equipment"),
    ("Janitorial Equipment", "Lobby Dust Pan, each", "Each", 11.00, 1.70, 3, 2, "Summitview Tool & Equipment"),
    ("Janitorial Equipment", "Spray Bottles 32 oz, pack of 12", "Pack", 13.00, 1.70, 5, 2, "Bayside Industrial Supply"),
    ("Janitorial Equipment", "Wet Floor Sign, each", "Each", 12.50, 1.70, 3, 2, "Summitview Tool & Equipment"),
    ("Janitorial Equipment", "Toilet Bowl Brush, pack of 6", "Pack", 15.00, 1.70, 3, 2, "Bayside Industrial Supply"),
    ("Janitorial Equipment", "Paper Towel Dispenser, each", "Each", 34.00, 1.60, 2, 1, "Prairie Wind Manufacturing"),
    ("Janitorial Equipment", "Soap Dispenser, each", "Each", 21.00, 1.65, 2, 2, "Prairie Wind Manufacturing"),
)  # fmt: skip

# customer group -> (customer names, discount off list price)
CUSTOMERS = {
    "Healthcare": (
        ("Maple Grove Family Clinic", "Riverside Dental Partners", "Cedar Hill Veterinary Hospital",
         "Lakeshore Physical Therapy", "Brookfield Urgent Care", "Willow Creek Senior Living",
         "Harborpoint Pediatrics", "Silver Pine Dialysis Center"),
        0.03,
    ),
    "Education": (
        ("Oak Valley School District", "Northgate Community College", "Hillcrest Montessori",
         "Westbrook Charter School", "Fairhaven Learning Center", "Pinewood Day Care",
         "Clearview Tutoring Center", "St. Aldric Academy"),
        0.05,
    ),
    "Hospitality": (
        ("Seaside Inn & Suites", "Copper Kettle Diner", "Grandview Banquet Hall", "Bluebird Coffee House",
         "Harvest Table Bistro", "Summit Lodge Hotel", "Juniper Grill", "Lantern Street Bakery"),
        0.02,
    ),
    "Facilities Management": (
        ("Crestline Facility Services", "Evergreen Building Maintenance", "Sparkpoint Commercial Cleaning",
         "Tri-County Janitorial", "Apex Property Care", "Lighthouse Building Services",
         "Meridian Office Services", "Stonebridge Custodial"),
        0.08,
    ),
    "Retail": (
        ("Corner Market Grocers", "Northside Hardware", "Petal & Stem Florist", "Main Street Pharmacy",
         "Two Rivers Auto Care", "Greenleaf Garden Center", "Riverbend Outfitters", "Sunrise Laundromat"),
        0.0,
    ),
}  # fmt: skip

# Customer group -> item groups it buys more of than average.
AFFINITY = {
    "Healthcare": {"Safety & PPE": 2.0, "Cleaning Chemicals": 1.5},
    "Education": {"Paper Products": 1.8, "Janitorial Equipment": 1.3},
    "Hospitality": {"Paper Products": 1.6, "Cleaning Chemicals": 1.3},
    "Facilities Management": {
        "Janitorial Equipment": 2.0,
        "Cleaning Chemicals": 1.5,
        "Liners & Packaging": 1.4,
    },
    "Retail": {"Liners & Packaging": 1.8},
}


@dataclass(frozen=True)
class Item:
    code: str
    name: str
    group: str
    uom: str
    cost: float
    price: float
    supplier: str
    popularity: int
    typical_qty: int
    reorder_level: int
    reorder_qty: int
    opening_qty: int


@dataclass(frozen=True)
class Customer:
    name: str
    group: str
    territory: str
    email: str
    pay_profile: str
    discount: float


@dataclass(frozen=True)
class Supplier:
    name: str
    group: str
    lead_days: int


@dataclass(frozen=True)
class Line:
    item_code: str
    qty: int
    rate: float

    @property
    def amount(self) -> float:
        return round(self.qty * self.rate, 2)


@dataclass(frozen=True)
class SalesOrder:
    key: str
    customer: str
    order_date: date
    delivery_date: date
    invoice_date: date | None  # None: not invoiced (shipped) by END
    payment_date: date | None  # None: unpaid as of END
    mode_of_payment: str
    lines: tuple[Line, ...]

    @property
    def due_date(self) -> date | None:
        return self.invoice_date + timedelta(days=NET_DAYS) if self.invoice_date else None

    @property
    def total(self) -> float:
        return round(sum(line.amount for line in self.lines), 2)


@dataclass(frozen=True)
class PurchaseOrder:
    key: str
    supplier: str
    order_date: date
    receipt_date: date  # expected date; received only if on or before END
    payment_date: date | None
    lines: tuple[Line, ...]

    @property
    def received(self) -> bool:
        return self.receipt_date <= END

    @property
    def due_date(self) -> date:
        return self.receipt_date + timedelta(days=NET_DAYS)

    @property
    def total(self) -> float:
        return round(sum(line.amount for line in self.lines), 2)


@dataclass(frozen=True)
class Step:
    """One ERPNext document to create, in the order the runner must create them."""

    kind: str
    day: date
    key: str


@dataclass(frozen=True)
class Dataset:
    items: tuple[Item, ...]
    customers: tuple[Customer, ...]
    suppliers: tuple[Supplier, ...]
    sales_orders: tuple[SalesOrder, ...]
    purchase_orders: tuple[PurchaseOrder, ...]
    closing_stock: dict[str, int]

    def item(self, code: str) -> Item:
        return next(i for i in self.items if i.code == code)


# Same-day order: stock arrives before it is sold, and invoices exist before they are paid.
STEP_ORDER = (
    "opening_stock",
    "opening_cash",
    "purchase_invoice",
    "purchase_order",
    "sales_order",
    "sales_invoice",
    "customer_payment",
    "supplier_payment",
)


def is_weekday(day: date) -> bool:
    return day.weekday() < 5


def add_business_days(day: date, days: int) -> date:
    while days > 0:
        day += timedelta(days=1)
        if is_weekday(day):
            days -= 1
    return day


def price_factor(day: date) -> float:
    return 1 + PRICE_INCREASE if day >= PRICE_INCREASE_DATE else 1.0


def slug(name: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in name.lower()).strip("-").replace("--", "-")


def _poisson(rng: random.Random, mean: float) -> int:
    """Knuth's method; fine for the small means used here."""
    limit, k, p = math.exp(-mean), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _weighted(rng: random.Random, options: dict) -> object:
    return rng.choices(list(options), weights=list(options.values()))[0]


def build_items() -> tuple[Item, ...]:
    """Catalog items, with reorder settings sized from expected weekly demand."""
    total_popularity = sum(row[5] for row in CATALOG)
    mean_lines = sum(n * w for n, w in LINES_PER_ORDER.items()) / sum(LINES_PER_ORDER.values())
    line_picks_per_week = ORDERS_PER_WEEKDAY * 5 * mean_lines
    counters = dict.fromkeys(ITEM_GROUPS, 0)
    items = []
    for group, name, uom, cost, markup, popularity, typical_qty, supplier in CATALOG:
        counters[group] += 1
        typical_qty *= QTY_SCALE
        weekly = line_picks_per_week * popularity / total_popularity * typical_qty * 1.05
        reorder_level = max(2, math.ceil(weekly * 2.5))  # covers lead time plus the next review
        reorder_qty = max(6, math.ceil(weekly * 6))
        items.append(
            Item(
                code=f"{ABBR}-{ITEM_GROUPS[group]}-{counters[group]:03d}",
                name=name,
                group=group,
                uom=uom,
                cost=cost,
                price=round(cost * markup, 2),
                supplier=supplier,
                popularity=popularity,
                typical_qty=typical_qty,
                reorder_level=reorder_level,
                reorder_qty=reorder_qty,
                opening_qty=reorder_level + reorder_qty,
            )
        )
    return tuple(items)


def build_customers(rng: random.Random) -> tuple[Customer, ...]:
    customers = []
    for group, (names, discount) in CUSTOMERS.items():
        for name in names:
            customers.append(
                Customer(
                    name=name,
                    group=group,
                    territory=rng.choice(TERRITORIES),
                    email=f"purchasing@{slug(name)}.example.com",
                    pay_profile=_weighted(rng, {k: w for k, (_, w) in PAY_PROFILES.items()}),
                    discount=discount,
                )
            )
    return tuple(customers)


def build_dataset(seed: int = SEED) -> Dataset:
    """Simulate START..END and return every record to seed. Same seed, same result."""
    rng = random.Random(seed)
    items = build_items()
    customers = build_customers(rng)
    suppliers = tuple(Supplier(*row) for row in SUPPLIERS)
    by_code = {item.code: item for item in items}
    supplier_by_name = {s.name: s for s in suppliers}

    # A few customers buy far more than the rest (roughly an 80/20 split).
    ranked = list(customers)
    rng.shuffle(ranked)
    customer_weight = {c.name: 1 / (rank + 1) ** 0.9 for rank, c in enumerate(ranked)}

    stock = {item.code: item.opening_qty for item in items}
    on_order = dict.fromkeys(stock, 0)
    arrivals: dict[date, list[PurchaseOrder]] = {}
    sales_orders: list[SalesOrder] = []
    purchase_orders: list[PurchaseOrder] = []

    day = START
    while day <= END:
        for po in arrivals.pop(day, []):
            for line in po.lines:
                stock[line.item_code] += line.qty
                on_order[line.item_code] -= line.qty

        if is_weekday(day):
            for _ in range(_poisson(rng, ORDERS_PER_WEEKDAY * SEASONALITY[day.month])):
                order = _sales_order(
                    rng, day, customers, customer_weight, items, stock, len(sales_orders)
                )
                if order:
                    sales_orders.append(order)
        if day.weekday() in REORDER_WEEKDAYS:
            for po in _reorders(
                rng, day, items, stock, on_order, supplier_by_name, len(purchase_orders)
            ):
                purchase_orders.append(po)
                arrivals.setdefault(po.receipt_date, []).append(po)
        day += timedelta(days=1)

    assert all(qty >= 0 for qty in stock.values()), "simulation oversold an item"
    assert set(by_code) == set(stock)
    return Dataset(
        items=items,
        customers=customers,
        suppliers=suppliers,
        sales_orders=tuple(sales_orders),
        purchase_orders=tuple(purchase_orders),
        closing_stock=stock,
    )


def _sales_order(rng, day, customers, customer_weight, items, stock, count) -> SalesOrder | None:
    customer = rng.choices(customers, weights=[customer_weight[c.name] for c in customers])[0]
    affinity = AFFINITY.get(customer.group, {})
    weights = [item.popularity * affinity.get(item.group, 1.0) for item in items]
    wanted = _weighted(rng, LINES_PER_ORDER)
    picked: list[Item] = []
    for _ in range(wanted * 3):  # draw until we have `wanted` distinct items (or give up)
        item = rng.choices(items, weights=weights)[0]
        if item not in picked:
            picked.append(item)
        if len(picked) == wanted:
            break

    lines = []
    for item in sorted(picked, key=lambda i: i.code):
        qty = min(max(1, round(item.typical_qty * rng.uniform(0.5, 1.6))), stock[item.code])
        if qty <= 0:
            continue  # out of stock: the line is lost, as it would be in real life
        stock[item.code] -= qty  # reserve now, so the later invoice can always ship
        rate = round(item.price * price_factor(day) * (1 - customer.discount), 2)
        lines.append(Line(item.code, qty, rate))
    if not lines:
        return None

    invoice_date = add_business_days(day, rng.randint(1, 3))
    payment_date = None
    if invoice_date <= END:
        low, high = PAY_PROFILES[customer.pay_profile][0]
        payment_date = invoice_date + timedelta(days=rng.randint(low, high))
        if payment_date > END:
            payment_date = None
    else:
        invoice_date = None
    return SalesOrder(
        key=f"{KEY_PREFIX}-SO-{count + 1:04d}",
        customer=customer.name,
        order_date=day,
        delivery_date=add_business_days(day, 3),
        invoice_date=invoice_date,
        payment_date=payment_date,
        mode_of_payment=_weighted(rng, MODES_OF_PAYMENT),
        lines=tuple(lines),
    )


def _reorders(rng, day, items, stock, on_order, supplier_by_name, count) -> list[PurchaseOrder]:
    """One purchase order per supplier for every item at or below its reorder level."""
    needed: dict[str, list[Item]] = {}
    for item in items:
        if day >= BACKORDER_FROM and item.code in BACKORDERED_ITEMS:
            continue
        if stock[item.code] + on_order[item.code] <= item.reorder_level:
            needed.setdefault(item.supplier, []).append(item)

    orders = []
    for supplier_name in sorted(needed):
        supplier = supplier_by_name[supplier_name]
        lines = []
        for item in needed[supplier_name]:
            on_order[item.code] += item.reorder_qty
            rate = round(item.cost * price_factor(day) * rng.uniform(0.98, 1.03), 2)
            lines.append(Line(item.code, item.reorder_qty, rate))
        receipt = add_business_days(day, max(1, supplier.lead_days + rng.randint(-1, 2)))
        payment = receipt + timedelta(days=NET_DAYS + rng.randint(-5, 5))
        orders.append(
            PurchaseOrder(
                key=f"{KEY_PREFIX}-PO-{count + len(orders) + 1:04d}",
                supplier=supplier_name,
                order_date=day,
                receipt_date=receipt,
                payment_date=payment if receipt <= END and payment <= END else None,
                lines=tuple(lines),
            )
        )
    return orders


def build_steps(dataset: Dataset) -> list[Step]:
    """Every transaction to create, in an order ERPNext accepts (stock never goes negative)."""
    steps = [
        Step("opening_stock", START, f"{KEY_PREFIX}-OPENING-STOCK"),
        Step("opening_cash", START, f"{KEY_PREFIX}-OPENING-CASH"),
    ]
    for po in dataset.purchase_orders:
        steps.append(Step("purchase_order", po.order_date, po.key))
        if po.received:
            steps.append(Step("purchase_invoice", po.receipt_date, po.key))
        if po.payment_date:
            steps.append(Step("supplier_payment", po.payment_date, po.key))
    for so in dataset.sales_orders:
        steps.append(Step("sales_order", so.order_date, so.key))
        if so.invoice_date:
            steps.append(Step("sales_invoice", so.invoice_date, so.key))
        if so.payment_date:
            steps.append(Step("customer_payment", so.payment_date, so.key))
    return sorted(steps, key=lambda s: (s.day, STEP_ORDER.index(s.kind), s.key))
