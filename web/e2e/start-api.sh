#!/usr/bin/env bash
# Starts the API for E2E: fresh database, migrations, and Example Bank (fictional, test_only) data ingested through
# the real pipeline from synthetic fixtures. Never used in production (E2E_TEST_DATA is refused when BANKREC_ENV=prod).
set -euo pipefail
cd "$(dirname "$0")/../.."
: "${E2E_DATABASE_URL:=postgresql+psycopg://bankrec:bankrec@localhost:5432/bankrec_e2e}"
export DATABASE_URL="$E2E_DATABASE_URL" BANKREC_ENV=dev E2E_TEST_DATA=1 WEB_ORIGIN="${WEB_ORIGIN:-http://127.0.0.1:3010}"
export BANKREC_DATA_DIR="${BANKREC_DATA_DIR:-/tmp/bankrec-e2e/data}" BANKREC_REPORTS_DIR="${BANKREC_REPORTS_DIR:-/tmp/bankrec-e2e/reports}"
export API_POST_RATE_LIMIT_PER_MINUTE=1000
PSQL_URL="${DATABASE_URL/+psycopg/}"
ADMIN_URL="${PSQL_URL%/*}/postgres"
psql "$ADMIN_URL" -qtc "DROP DATABASE IF EXISTS bankrec_e2e WITH (FORCE)" >/dev/null
psql "$ADMIN_URL" -qtc "CREATE DATABASE bankrec_e2e" >/dev/null
uv run --frozen bankrec db upgrade >/dev/null
uv run --frozen bankrec ingest --include-test --bank example_bank >/dev/null
exec uv run --frozen bankrec api serve --host 127.0.0.1 --port "${API_PORT:-8010}"
