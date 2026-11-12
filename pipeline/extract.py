"""Copy ERPNext records into the raw schema, incrementally and safely rerunnable.

For each parent doctype (Customer, Sales Invoice, ...):
1. Fetch the records ERPNext changed since the last successful load (its "modified" watermark),
   or every record in --full mode.
2. Fetch the child rows (invoice lines, payment references, ...) of exactly those records. A child
   row's own "modified" is not updated when only its parent changes, so children are always
   reloaded through their parent.
3. In one database transaction: upsert the records, replace their child rows, and advance the
   watermark. A failed run leaves each table as it was before that doctype started.

Incremental runs can't see records deleted in ERPNext (rare for submitted documents). Run with
--full now and then to rebuild the raw copies from scratch.
"""

from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Any, Protocol

from psycopg import Connection, sql
from psycopg.types.json import Jsonb

from pipeline.entities import PARENTS, Entity, children_of

CHILD_CHUNK = 100  # parent names per child-table request, to keep URLs short


class Erp(Protocol):
    def get_list(self, doctype, fields=..., filters=..., parent=...) -> list[dict[str, Any]]: ...


class RawStore(Protocol):
    """Where raw rows go. Postgres in real runs, an in-memory fake in unit tests."""

    def transaction(self) -> AbstractContextManager: ...
    def watermark(self, doctype: str) -> datetime | None: ...
    def truncate(self, entity: Entity) -> None: ...
    def delete_children(self, entity: Entity, parent_names: Sequence[str]) -> None: ...
    def upsert(self, entity: Entity, rows: Sequence[dict[str, Any]], run_id: str) -> None: ...
    def set_watermark(self, doctype: str, value: datetime, run_id: str) -> None: ...


def parse_modified(value: str) -> datetime:
    """ERPNext timestamps look like '2026-11-12 10:28:51.556667' (site time, no zone)."""
    return datetime.fromisoformat(value)


def chunks(items: Sequence[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(items), size):
        yield list(items[start : start + size])


def load_entity(
    erp: Erp, store: RawStore, entity: Entity, run_id: str, full: bool = False
) -> dict[str, int]:
    """Load one parent doctype and its child tables. Returns rows loaded per doctype."""
    since = None if full else store.watermark(entity.doctype)
    filters = [["modified", ">=", str(since)]] if since else None
    rows = erp.get_list(entity.doctype, fields=["*"], filters=filters)
    names = [row["name"] for row in rows]

    children = children_of(entity.doctype)
    child_rows: dict[Entity, list[dict[str, Any]]] = {child: [] for child in children}
    for child in children:
        for chunk in chunks(names, CHILD_CHUNK):
            child_rows[child].extend(
                erp.get_list(
                    child.doctype,
                    fields=["*"],
                    filters=[["parent", "in", chunk]],
                    parent=entity.doctype,
                )
            )

    with store.transaction():
        if full:
            store.truncate(entity)
            for child in children:
                store.truncate(child)
        store.upsert(entity, rows, run_id)
        for child in children:
            store.delete_children(child, names)
            store.upsert(child, child_rows[child], run_id)
        if rows:
            newest = max(parse_modified(row["modified"]) for row in rows)
            store.set_watermark(entity.doctype, newest, run_id)

    return {entity.doctype: len(rows), **{c.doctype: len(r) for c, r in child_rows.items()}}


def load_all(
    erp: Erp, store: RawStore, run_id: str, full: bool = False, log=None
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entity in PARENTS:
        loaded = load_entity(erp, store, entity, run_id, full)
        counts.update(loaded)
        if log:
            log.info("Loaded", extra={"doctype": entity.doctype, "rows": loaded, "full": full})
    return counts


class PostgresStore:
    """RawStore backed by the raw and ops schemas."""

    def __init__(self, conn: Connection):
        self.conn = conn

    def transaction(self) -> AbstractContextManager:
        return self.conn.transaction()

    def watermark(self, doctype: str) -> datetime | None:
        row = self.conn.execute(
            "SELECT last_modified FROM ops.pipeline_watermarks WHERE entity = %s", (doctype,)
        ).fetchone()
        return row[0] if row else None

    def _table(self, entity: Entity) -> sql.Identifier:
        return sql.Identifier("raw", entity.table)

    def truncate(self, entity: Entity) -> None:
        self.conn.execute(sql.SQL("TRUNCATE {}").format(self._table(entity)))

    def delete_children(self, entity: Entity, parent_names: Sequence[str]) -> None:
        if parent_names:
            self.conn.execute(
                sql.SQL("DELETE FROM {} WHERE parent = ANY(%s)").format(self._table(entity)),
                (list(parent_names),),
            )

    def upsert(self, entity: Entity, rows: Sequence[dict[str, Any]], run_id: str) -> None:
        if not rows:
            return
        statement = sql.SQL(
            """INSERT INTO {} (name, parent, modified, docstatus, data, run_id)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (name) DO UPDATE SET
                   parent = EXCLUDED.parent, modified = EXCLUDED.modified,
                   docstatus = EXCLUDED.docstatus, data = EXCLUDED.data,
                   run_id = EXCLUDED.run_id, loaded_at = now()"""
        ).format(self._table(entity))
        with self.conn.cursor() as cur:
            cur.executemany(
                statement,
                [
                    (
                        row["name"],
                        row.get("parent") if entity.parent else None,
                        parse_modified(row["modified"]),
                        row.get("docstatus"),
                        Jsonb(row),
                        run_id,
                    )
                    for row in rows
                ],
            )

    def set_watermark(self, doctype: str, value: datetime, run_id: str) -> None:
        self.conn.execute(
            """INSERT INTO ops.pipeline_watermarks (entity, last_modified, run_id)
               VALUES (%s, %s, %s)
               ON CONFLICT (entity) DO UPDATE SET
                   last_modified = GREATEST(
                       ops.pipeline_watermarks.last_modified, EXCLUDED.last_modified
                   ),
                   updated_at = now(), run_id = EXCLUDED.run_id""",
            (doctype, value, run_id),
        )
