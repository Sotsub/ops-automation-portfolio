#!/usr/bin/env bash
# Bluefield Supply Co. database setup. Demo data only.
#
# Creates:
#   - reporting schemas raw, staging, marts, ops in the main database ($POSTGRES_DB)
#   - a "metabase" role and database for Metabase's own app data
#   - an "n8n" role and database for n8n's own app data
#   - a "reporting_reader" role that can only read the marts schema (Project 1)
#   - an "ai" schema of approved views and an "ai_reader" role that can only read them (Project 2)
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
: "${AI_READER_PASSWORD:?AI_READER_PASSWORD is not set (run make env-secrets, then recreate postgres with make up)}"
: "${REPORTING_READER_PASSWORD:?REPORTING_READER_PASSWORD is not set (run make env-secrets, then recreate postgres with make up)}"

psql -v ON_ERROR_STOP=1 --no-psqlrc \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  -v reporting_db="$POSTGRES_DB" \
  -v metabase_pw="$METABASE_DB_PASSWORD" \
  -v n8n_pw="$N8N_DB_PASSWORD" \
  -v admin_role="$POSTGRES_USER" \
  -v reader_pw="$REPORTING_READER_PASSWORD" \
  -v ai_pw="$AI_READER_PASSWORD" <<'SQL'

-- Reporting schemas for Bluefield business data.
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS marts;
CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS ai;

COMMENT ON SCHEMA raw IS 'Copies of ERPNext API data, loaded by the pipeline. Demo data only.';
COMMENT ON SCHEMA staging IS 'Cleaned and typed models built by dbt. Demo data only.';
COMMENT ON SCHEMA marts IS 'Reporting tables used by dashboards, reports, and AI. Demo data only.';
COMMENT ON SCHEMA ops IS 'Run history, audit logs, inboxes, and other operational tables.';
COMMENT ON SCHEMA ai IS 'Approved views the AI assistant may read (built by dbt). Demo data only.';

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

-- Read-only reporting login (Project 1). It can read marts and nothing else: no raw, staging or
-- ops data, no writes. Dashboards (and later the AI assistant) use it instead of the admin login.
SELECT 'CREATE ROLE reporting_reader LOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'reporting_reader') \gexec
ALTER ROLE reporting_reader WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'reader_pw';
ALTER ROLE reporting_reader SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE :"reporting_db" TO reporting_reader;
REVOKE ALL ON SCHEMA public, raw, staging, ops FROM reporting_reader;
GRANT USAGE ON SCHEMA marts TO reporting_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA marts TO reporting_reader;
-- dbt rebuilds the marts tables as the admin role, so new tables must be readable too.
ALTER DEFAULT PRIVILEGES FOR ROLE :"admin_role" IN SCHEMA marts GRANT SELECT ON TABLES TO reporting_reader;

-- AI assistant login (Project 2). It reads the approved views in the ai schema and nothing else:
-- not marts, raw, staging or ops. The views run with their owner's rights, so the assistant needs
-- no access to the tables underneath. Sessions are read-only and stop any query after 5 seconds.
SELECT 'CREATE ROLE ai_reader LOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ai_reader') \gexec
ALTER ROLE ai_reader WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'ai_pw';
ALTER ROLE ai_reader SET default_transaction_read_only = on;
ALTER ROLE ai_reader SET statement_timeout = '5s';
GRANT CONNECT ON DATABASE :"reporting_db" TO ai_reader;
REVOKE ALL ON SCHEMA public, raw, staging, marts, ops FROM ai_reader;
GRANT USAGE ON SCHEMA ai TO ai_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA ai TO ai_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE :"admin_role" IN SCHEMA ai GRANT SELECT ON TABLES TO ai_reader;
SQL

echo "bluefield init: schemas, app roles, app databases, and the reporting and AI readers are ready."
