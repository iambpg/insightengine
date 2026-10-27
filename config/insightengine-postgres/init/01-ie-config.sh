#!/bin/bash
# Runs only when the insightengine-postgres data volume is empty.
# Passwords are hex from install.sh (no quotes or spaces), so they are safe to interpolate here.
set -euo pipefail
if [ -z "${IE_CONFIG_DB_PASSWORD:-}" ]; then
  echo "IE_CONFIG_DB_PASSWORD is empty; skipping ie_config role" >&2
  exit 0
fi
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
CREATE USER ie_config WITH PASSWORD '${IE_CONFIG_DB_PASSWORD}';
CREATE DATABASE ie_config OWNER ie_config;
EOSQL
# Optional analytics databases used by the Grafana datasource placeholders.
if [ -n "${TELEGRAF_PG_PASSWORD:-}" ]; then
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
CREATE USER telegraf_data WITH PASSWORD '${TELEGRAF_PG_PASSWORD}';
CREATE DATABASE telegraf_data OWNER telegraf_data;
EOSQL
fi
if [ -n "${AP_DATA_PASSWORD:-}" ]; then
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
CREATE USER activepieces_data WITH PASSWORD '${AP_DATA_PASSWORD}';
CREATE DATABASE activepieces_data OWNER activepieces_data;
EOSQL
fi
