#!/usr/bin/env bash
# Bluefield Supply Co. database setup. Demo data only.
#
# Creates:
#   - reporting schemas raw, staging, marts, ops in the main database ($POSTGRES_DB)
#   - a "metabase" role and database for Metabase's own app data
#   - an "n8n" role and database for n8n's own app data
#
# Runs automatically the first time Postgres starts with an empty volume.
# Safe to rerun at any time (make db-init): every step checks before it creates,
# and role passwords are reset to the current .env values.
#
# Passwords go to psql as variables (:'name'), so they are quoted by psql and
# never pasted into SQL text by the shell.

set -Eeo pipefail

: "${POSTGRES_USER:?POSTGRES_USER is not set}"
: "${POSTGRES_DB:?POSTGRES_DB is not set}"
: "${METABASE_DB_PASSWORD:?METABASE_DB_PASSWORD is not set}"
: "${N8N_DB_PASSWORD:?N8N_DB_PASSWORD is not set}"

psql -v ON_ERROR_STOP=1 --no-psqlrc \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  -v reporting_db="$POSTGRES_DB" \
  -v metabase_pw="$METABASE_DB_PASSWORD" \
  -v n8n_pw="$N8N_DB_PASSWORD" <<'SQL'

-- Reporting schemas for Bluefield business data.
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS marts;
CREATE SCHEMA IF NOT EXISTS ops;

COMMENT ON SCHEMA raw IS 'Copies of ERPNext API data, loaded by the pipeline. Demo data only.';
COMMENT ON SCHEMA staging IS 'Cleaned and typed models built by dbt. Demo data only.';
COMMENT ON SCHEMA marts IS 'Reporting tables used by dashboards, reports, and AI. Demo data only.';
COMMENT ON SCHEMA ops IS 'Run history, audit logs, inboxes, and other operational tables.';

-- App roles. CREATE ROLE has no IF NOT EXISTS, so build it only when missing.
SELECT 'CREATE ROLE metabase LOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'metabase') \gexec
ALTER ROLE metabase WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'metabase_pw';

SELECT 'CREATE ROLE n8n LOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'n8n') \gexec
ALTER ROLE n8n WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'n8n_pw';

-- App databases, each owned by its own role.
SELECT 'CREATE DATABASE metabase OWNER metabase'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'metabase') \gexec
SELECT 'CREATE DATABASE n8n OWNER n8n'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'n8n') \gexec

-- Only named roles may connect. Later projects grant CONNECT on the reporting
-- database to specific read-only roles (for example, Metabase's reporting user).
REVOKE CONNECT, TEMPORARY ON DATABASE :"reporting_db" FROM PUBLIC;
REVOKE CONNECT, TEMPORARY ON DATABASE metabase FROM PUBLIC;
REVOKE CONNECT, TEMPORARY ON DATABASE n8n FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE metabase TO metabase;
GRANT CONNECT, TEMPORARY ON DATABASE n8n TO n8n;
SQL

echo "bluefield init: schemas, app roles, and app databases are ready."
