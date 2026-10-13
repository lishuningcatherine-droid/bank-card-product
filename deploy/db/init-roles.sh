#!/usr/bin/env bash
# Postgres container init: creates the read-only API role with the password from API_DB_PASSWORD.
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bankrec_api') THEN
    CREATE ROLE bankrec_api LOGIN PASSWORD '${API_DB_PASSWORD}';
  END IF;
END \$\$;
SQL
