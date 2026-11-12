"""Postgres connection and the tables the pipeline owns (raw copies of ERPNext, run history)."""

import psycopg

from pipeline.entities import ENTITIES, Entity
from shared.config import Settings


def connect(settings: Settings) -> psycopg.Connection:
    """Connect to the reporting database as the admin role (the pipeline writes raw and ops)."""
    if settings.postgres_password is None:
        raise SystemExit(
            "POSTGRES_PASSWORD is blank in .env. Run `make env-secrets`, then `make up`."
        )
    return psycopg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password.get_secret_value(),
        application_name="bluefield-pipeline",
    )


def raw_table_ddl(entity: Entity) -> str:
    table = f"raw.{entity.table}"
    return f"""
CREATE TABLE IF NOT EXISTS {table} (
    name text PRIMARY KEY,
    parent text,
    modified timestamp NOT NULL,
    docstatus smallint,
    data jsonb NOT NULL,
    run_id text NOT NULL,
    loaded_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS {entity.table}_parent_idx ON {table} (parent);
COMMENT ON TABLE {table} IS
    'ERPNext "{entity.doctype}" records exactly as the REST API returned them. Demo data only.';
"""


OPS_DDL = """
CREATE TABLE IF NOT EXISTS ops.pipeline_runs (
    run_id text PRIMARY KEY,
    pipeline text NOT NULL,
    mode text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    status text NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    rows_loaded jsonb,
    error text
);
COMMENT ON TABLE ops.pipeline_runs IS 'One row per pipeline run: mode, outcome, and rows loaded.';

CREATE TABLE IF NOT EXISTS ops.pipeline_watermarks (
    entity text PRIMARY KEY,
    last_modified timestamp NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    run_id text NOT NULL
);
COMMENT ON TABLE ops.pipeline_watermarks IS
    'Latest ERPNext "modified" timestamp loaded per doctype. The next run fetches from here.';
"""


def ensure_tables(conn: psycopg.Connection) -> None:
    """Create every pipeline table that is missing. Safe to run every time."""
    with conn.transaction():
        conn.execute(OPS_DDL)
        for entity in ENTITIES:
            conn.execute(raw_table_ddl(entity))
