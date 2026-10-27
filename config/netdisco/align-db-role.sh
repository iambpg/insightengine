#!/bin/bash
# Align the Netdisco application role with NETDISCO_DB_NAME / NETDISCO_DB_USER /
# NETDISCO_DB_PASS. Runs once per start, as the postgres OS user, over the
# shared unix socket.
#
# Upstream netdisco-db-entrypoint.sh replaces POSTGRES_PASSWORD with a random
# superuser password whenever PGDATA has no PG_VERSION. netdisco-initdb.sh then
# CREATE ROLE's the app user from NETDISCO_DB_* (default password "netdisco" only
# when NETDISCO_DB_PASS is unset) with ON_ERROR_STOP=0. That CREATE ROLE is a
# no-op if POSTGRES_USER was already "netdisco", and init scripts do not run
# again once PG_VERSION exists. This script re-applies the app password on the
# local trust socket so backend, web, db-init, and ie-config all use one value.
# The password is not printed.
set -euo pipefail

: "${NETDISCO_DB_NAME:?}"
: "${NETDISCO_DB_USER:?}"
: "${NETDISCO_DB_PASS:?}"

export PGHOST="${PGHOST:-/var/run/postgresql}"
unset PGUSER PGPASSWORD || true

i=0
until psql -U postgres -d template1 -v ON_ERROR_STOP=1 -c 'SELECT 1' >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -ge 30 ]; then
    echo "postgres socket not available for the netdisco app role" >&2
    exit 1
  fi
  sleep 1
done

# %I / %L quote the identifier and the password. psql does not echo the statement.
psql -U postgres -d template1 -v ON_ERROR_STOP=1 \
  -v role="$NETDISCO_DB_USER" -v pass="$NETDISCO_DB_PASS" -v dbname="$NETDISCO_DB_NAME" <<'SQL'
SELECT format(
  'CREATE ROLE %I WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L',
  :'role', :'pass')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'role')
\gexec
SELECT format(
  'ALTER ROLE %I WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L',
  :'role', :'pass')
\gexec
SELECT format('CREATE DATABASE %I OWNER %I', :'dbname', :'role')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'dbname')
\gexec
SELECT format('ALTER DATABASE %I OWNER TO %I', :'dbname', :'role')
\gexec
SQL

psql -U postgres -d template1 -v ON_ERROR_STOP=1 \
  -v role="$NETDISCO_DB_USER" -v dbname="$NETDISCO_DB_NAME" <<'SQL'
SELECT format('GRANT ALL PRIVILEGES ON DATABASE %I TO %I', :'dbname', :'role')
\gexec
SQL

echo "netdisco app role is aligned with NETDISCO_DB_USER/NETDISCO_DB_NAME" >&2
