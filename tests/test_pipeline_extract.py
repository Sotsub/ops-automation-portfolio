"""Incremental loading into raw, tested with a fake ERPNext and an in-memory store (no services)."""

from contextlib import contextmanager
from datetime import datetime

import pytest

from pipeline import extract
from pipeline.entities import ENTITIES, PARENTS, Entity, children_of

INVOICE = next(e for e in ENTITIES if e.doctype == "Sales Invoice")
LINE = next(e for e in ENTITIES if e.doctype == "Sales Invoice Item")


class FakeErp:
    """Holds records per doctype and answers get_list like the REST API (subset of filters)."""

    def __init__(self):
        self.records: dict[str, list[dict]] = {}
        self.calls: list[tuple[str, list | None, str | None]] = []
        self.fail_on: str | None = None

    def add(self, doctype, name, modified, parent=None, **data):
        row = {"name": name, "modified": modified, "docstatus": 1, **data}
        if parent:
            row["parent"] = parent
        self.records.setdefault(doctype, []).append(row)
        return row

    def get_list(self, doctype, fields=("name",), filters=None, parent=None):
        self.calls.append((doctype, filters, parent))
        if self.fail_on == doctype:
            raise RuntimeError("ERPNext unavailable")
        rows = self.records.get(doctype, [])
        for field, op, value in filters or []:
            if op == ">=":
                rows = [
                    r
                    for r in rows
                    if extract.parse_modified(r[field]) >= extract.parse_modified(value)
                ]
            elif op == "in":
                rows = [r for r in rows if r[field] in value]
            else:
                raise AssertionError(op)
        return [dict(r) for r in rows]


class FakeStore:
    def __init__(self):
        self.tables: dict[str, dict[str, dict]] = {}
        self.watermarks: dict[str, datetime] = {}

    @contextmanager
    def transaction(self):
        snapshot = ({k: dict(v) for k, v in self.tables.items()}, dict(self.watermarks))
        try:
            yield
        except Exception:
            self.tables, self.watermarks = snapshot
            raise

    def watermark(self, doctype):
        return self.watermarks.get(doctype)

    def truncate(self, entity):
        self.tables[entity.table] = {}

    def delete_children(self, entity, parent_names):
        table = self.tables.setdefault(entity.table, {})
        for name in [n for n, r in table.items() if r["parent"] in parent_names]:
            del table[name]

    def upsert(self, entity, rows, run_id):
        table = self.tables.setdefault(entity.table, {})
        for row in rows:
            table[row["name"]] = {**row, "run_id": run_id}

    def set_watermark(self, doctype, value, run_id):
        self.watermarks[doctype] = max(value, self.watermarks.get(doctype, value))


@pytest.fixture
def erp():
    erp = FakeErp()
    erp.add("Sales Invoice", "SINV-1", "2026-01-05 10:00:00.000001")
    erp.add("Sales Invoice", "SINV-2", "2026-01-06 09:00:00")
    erp.add("Sales Invoice Item", "L1", "2026-01-05 10:00:00", parent="SINV-1", qty=1)
    erp.add("Sales Invoice Item", "L2", "2026-01-05 10:00:00", parent="SINV-1", qty=2)
    erp.add("Sales Invoice Item", "L3", "2026-01-06 09:00:00", parent="SINV-2", qty=3)
    return erp


def test_first_load_takes_everything_and_sets_the_watermark(erp):
    store = FakeStore()
    counts = extract.load_entity(erp, store, INVOICE, "run1")
    assert counts == {"Sales Invoice": 2, "Sales Invoice Item": 3}
    assert set(store.tables[LINE.table]) == {"L1", "L2", "L3"}
    assert store.watermarks["Sales Invoice"] == datetime(2026, 1, 6, 9, 0)
    assert erp.calls[0] == ("Sales Invoice", None, None)


def test_next_load_asks_only_for_changes_and_reloads_their_lines(erp):
    store = FakeStore()
    extract.load_entity(erp, store, INVOICE, "run1")
    # A payment updates SINV-1 (its lines keep their old "modified"), and line L2 is removed.
    erp.records["Sales Invoice"][0]["modified"] = "2026-02-01 08:00:00"
    erp.records["Sales Invoice Item"] = [
        r for r in erp.records["Sales Invoice Item"] if r["name"] != "L2"
    ]
    erp.calls.clear()

    counts = extract.load_entity(erp, store, INVOICE, "run2")

    assert erp.calls[0] == ("Sales Invoice", [["modified", ">=", "2026-01-06 09:00:00"]], None)
    assert erp.calls[1] == (
        "Sales Invoice Item",
        [["parent", "in", ["SINV-1", "SINV-2"]]],
        "Sales Invoice",
    )
    assert counts == {"Sales Invoice": 2, "Sales Invoice Item": 2}
    assert set(store.tables[LINE.table]) == {"L1", "L3"}, "lines of reloaded invoices are replaced"
    assert store.tables[INVOICE.table]["SINV-1"]["run_id"] == "run2"
    assert store.watermarks["Sales Invoice"] == datetime(2026, 2, 1, 8, 0)


def test_rerun_with_no_changes_keeps_everything(erp):
    store = FakeStore()
    extract.load_entity(erp, store, INVOICE, "run1")
    before = {k: dict(v) for k, v in store.tables.items()}
    extract.load_entity(erp, store, INVOICE, "run2")
    assert {k: set(v) for k, v in store.tables.items()} == {k: set(v) for k, v in before.items()}


def test_full_load_drops_records_deleted_in_erpnext(erp):
    store = FakeStore()
    extract.load_entity(erp, store, INVOICE, "run1")
    erp.records["Sales Invoice"] = [
        r for r in erp.records["Sales Invoice"] if r["name"] != "SINV-2"
    ]
    erp.records["Sales Invoice Item"] = [
        r for r in erp.records["Sales Invoice Item"] if r["parent"] != "SINV-2"
    ]
    extract.load_entity(erp, store, INVOICE, "run2", full=True)
    assert set(store.tables[INVOICE.table]) == {"SINV-1"}
    assert set(store.tables[LINE.table]) == {"L1", "L2"}


def test_child_rows_are_requested_in_chunks(monkeypatch):
    monkeypatch.setattr(extract, "CHILD_CHUNK", 2)
    erp = FakeErp()
    for i in range(5):
        erp.add("Sales Invoice", f"S{i}", "2026-01-01 00:00:00")
    extract.load_entity(erp, FakeStore(), INVOICE, "run1")
    child_calls = [c for c in erp.calls if c[0] == "Sales Invoice Item"]
    assert [len(c[1][0][2]) for c in child_calls] == [2, 2, 1]


def test_failed_fetch_changes_nothing(erp):
    store = FakeStore()
    extract.load_entity(erp, store, INVOICE, "run1")
    snapshot = ({k: dict(v) for k, v in store.tables.items()}, dict(store.watermarks))
    erp.records["Sales Invoice"][0]["modified"] = "2026-03-01 00:00:00"
    erp.fail_on = "Sales Invoice Item"
    with pytest.raises(RuntimeError):
        extract.load_entity(erp, store, INVOICE, "run2")
    assert (store.tables, store.watermarks) == snapshot


def test_load_all_covers_every_parent_and_child():
    erp = FakeErp()
    counts = extract.load_all(erp, FakeStore(), "run1")
    assert set(counts) == {e.doctype for e in ENTITIES}
    assert [c[0] for c in erp.calls if c[2] is None] == [e.doctype for e in PARENTS]


def test_entities_are_well_formed():
    tables = [e.table for e in ENTITIES]
    assert len(tables) == len(set(tables))
    assert all(t.startswith("erpnext_") and t.isidentifier() for t in tables)
    for entity in ENTITIES:
        if entity.parent:
            assert entity.parent in {p.doctype for p in PARENTS}
            assert entity in children_of(entity.parent)


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2026-11-12 10:28:51.556667", datetime(2026, 11, 12, 10, 28, 51, 556667)),
        ("2026-11-12 10:28:51", datetime(2026, 11, 12, 10, 28, 51)),
    ],
)
def test_parse_modified(value, expected):
    assert extract.parse_modified(value) == expected


def test_entity_type_is_hashable_for_child_maps():
    assert {Entity("A", "erpnext_a"): 1}
