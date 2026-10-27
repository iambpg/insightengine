#!/bin/bash
set -e

echo "Creating analytical data databases..."

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$AP_DATA_USER') THEN
            CREATE ROLE "$AP_DATA_USER" LOGIN PASSWORD '$AP_DATA_PASSWORD';
        END IF;
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$TELEGRAF_PG_USER') THEN
            CREATE ROLE "$TELEGRAF_PG_USER" LOGIN PASSWORD '$TELEGRAF_PG_PASSWORD';
        END IF;
    END
    \$\$;
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -tAc "SELECT 1 FROM pg_database WHERE datname = '$AP_DATA_DB'" | grep -q 1 || \
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -c "CREATE DATABASE \"$AP_DATA_DB\" OWNER \"$AP_DATA_USER\""

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -tAc "SELECT 1 FROM pg_database WHERE datname = '$TELEGRAF_PG_DB'" | grep -q 1 || \
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -c "CREATE DATABASE \"$TELEGRAF_PG_DB\" OWNER \"$TELEGRAF_PG_USER\""

echo "Analytical data databases ready."
