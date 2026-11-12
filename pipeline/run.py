"""Run the ERP-to-reporting pipeline: ERPNext -> raw -> (dbt) staging -> marts.

Usage:
    uv run python -m pipeline.run              # incremental load, then dbt build
    uv run python -m pipeline.run --full       # reload every raw table from scratch, then dbt build
    uv run python -m pipeline.run --skip-dbt   # load raw only
    uv run python -m pipeline.run --dbt-only   # rebuild staging and marts from what is in raw

Every run gets a run_id, writes JSON logs, and records its outcome in ops.pipeline_runs.
Safe to rerun: loads are upserts, and dbt rebuilds its tables each time.
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from erp.client import ErpClient, ErpError
from pipeline import db
from pipeline.extract import PostgresStore, load_all
from shared.config import Settings
from shared.logging import get_logger, new_run_id

PIPELINE = "erp_to_reporting"
DBT_DIR = Path(__file__).resolve().parent / "dbt"


class DbtFailed(Exception):
    pass


def dbt_env(settings: Settings, run_id: str) -> dict[str, str]:
    """Connection details for profiles.yml. Set in this process only, never printed."""
    if settings.postgres_password is None:
        raise SystemExit("POSTGRES_PASSWORD is blank in .env. Run `make env-secrets`.")
    return {
        "BLUEFIELD_PG_HOST": settings.postgres_host,
        "BLUEFIELD_PG_PORT": str(settings.postgres_port),
        "BLUEFIELD_PG_DB": settings.postgres_db,
        "BLUEFIELD_PG_USER": settings.postgres_user,
        "BLUEFIELD_PG_PASSWORD": settings.postgres_password.get_secret_value(),
        "BLUEFIELD_RUN_ID": run_id,
    }


def run_dbt(settings: Settings, run_id: str, log, command: str = "build") -> dict[str, int]:
    """Run `dbt build` (models plus tests). Raises DbtFailed if any model or test fails."""
    from dbt.cli.main import dbtRunner  # imported here so --skip-dbt runs don't load dbt

    os.environ.update(dbt_env(settings, run_id))
    args = [
        command,
        "--project-dir", str(DBT_DIR),
        "--profiles-dir", str(DBT_DIR),
        "--log-format", "json",
        "--quiet",
    ]  # fmt: skip
    result = dbtRunner().invoke(args)
    if result.exception is not None:
        raise DbtFailed(f"dbt could not run: {result.exception}")
    statuses: dict[str, int] = {}
    failures = []
    for node in result.result or []:
        status = str(node.status)
        statuses[status] = statuses.get(status, 0) + 1
        if status in ("error", "fail"):
            failures.append({"node": node.node.unique_id, "message": (node.message or "")[:300]})
    log.info("dbt finished", extra={"command": command, "statuses": statuses, "failures": failures})
    if not result.success:
        raise DbtFailed(f"dbt {command} failed: {failures}")
    return statuses


def record_start(conn, run_id: str, mode: str) -> None:
    with conn.transaction():
        conn.execute(
            """INSERT INTO ops.pipeline_runs (run_id, pipeline, mode, status)
               VALUES (%s, %s, %s, 'running')""",
            (run_id, PIPELINE, mode),
        )


def record_end(
    conn, run_id: str, status: str, rows: dict[str, Any], error: str | None = None
) -> None:
    with conn.transaction():
        conn.execute(
            """UPDATE ops.pipeline_runs
               SET status = %s, finished_at = now(), rows_loaded = %s, error = %s
               WHERE run_id = %s""",
            (status, Jsonb(rows), error, run_id),
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ERPNext -> Postgres reporting pipeline")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--skip-dbt", action="store_true", help="load raw tables only")
    group.add_argument("--dbt-only", action="store_true", help="skip ERPNext; rebuild from raw")
    parser.add_argument("--full", action="store_true", help="reload every raw table from scratch")
    args = parser.parse_args(argv)

    settings = Settings()
    run_id = new_run_id()
    log = get_logger("pipeline.run", run_id, settings.log_level)
    mode = "dbt-only" if args.dbt_only else ("full" if args.full else "incremental")

    with db.connect(settings) as conn:
        conn.autocommit = True  # each step manages its own transaction
        db.ensure_tables(conn)
        record_start(conn, run_id, mode)
        log.info("Pipeline started", extra={"mode": mode, "skip_dbt": args.skip_dbt})
        rows: dict[str, Any] = {}
        try:
            if not args.dbt_only:
                if not (settings.erpnext_api_key and settings.erpnext_api_secret):
                    raise SystemExit(
                        "ERPNEXT_API_KEY/SECRET are blank in .env. Run `make erp-api-keys`."
                    )
                with ErpClient(
                    settings.erpnext_url,
                    settings.erpnext_api_key.get_secret_value(),
                    settings.erpnext_api_secret.get_secret_value(),
                ) as erp:
                    rows = load_all(erp, PostgresStore(conn), run_id, full=args.full, log=log)
            if not args.skip_dbt:
                rows["dbt"] = run_dbt(settings, run_id, log)
        except (ErpError, DbtFailed, SystemExit, Exception) as exc:
            record_end(conn, run_id, "failed", rows, str(exc)[:2000])
            log.error("Pipeline failed", extra={"error": str(exc)[:2000]})
            return 1
        record_end(conn, run_id, "succeeded", rows)
        log.info("Pipeline finished", extra={"rows": rows})
    return 0


if __name__ == "__main__":
    sys.exit(main())
