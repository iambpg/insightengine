#!/bin/bash
# Align the Netdisco application role with NETDISCO_DB_NAME / NETDISCO_DB_USER /
# NETDISCO_DB_PASS. Runs once per start, as the postgres OS user, over the
# shared unix socket (local trust).
#
# A fresh Netdisco Postgres cluster has superuser role "postgres". A volume
# created with POSTGRES_USER=netdisco has superuser role "netdisco" and no
# "postgres" role. This script tries postgres, then NETDISCO_DB_USER, then any
# other login role with rolsuper. A missing socket is retried. A missing role
# or an authentication failure tries the next role, and the psql error is
# printed. The password is never printed.
#
# If the app role is itself the superuser, only its password is changed. It is
# not demoted.
set -euo pipefail

export PGHOST="${PGHOST:-/var/run/postgresql}"
unset PGUSER PGPASSWORD || true

WAIT_SECS="${NETDISCO_ROLE_WAIT:-30}"
SLEEP_SECS="${NETDISCO_ROLE_SLEEP:-1}"

redact() {
  local data
  data="$(cat)"
  if [ -n "${NETDISCO_DB_PASS:-}" ]; then
    data="${data//"$NETDISCO_DB_PASS"/[redacted]}"
  fi
  printf '%s\n' "$data"
}

# retry: the server socket is not accepting connections yet.
# next: this role cannot be used; try another.
err_kind() {
  local text
  text="$(cat "$1" 2>/dev/null || true)"
  case "$text" in
    *"No such file or directory"*|*"Connection refused"*|*"Is the server running"*|\
*"the database system is starting up"*|*"the database system is shutting down"*|\
*"could not connect to server"*|*"server closed the connection unexpectedly"*|\
*"Connection timed out"*|*"timeout expired"*)
      printf '%s' retry
      ;;
    *"does not exist"*|*"authentication failed"*|*"no pg_hba.conf entry"*)
      printf '%s' next
      ;;
    "")
      printf '%s' retry
      ;;
    *)
      printf '%s' next
      ;;
  esac
}

try_connect() {
  local user=$1 errfile=$2
  psql -U "$user" -d template1 -v ON_ERROR_STOP=1 -c 'SELECT 1' >/dev/null 2>"$errfile"
}

is_super() {
  local user=$1 ans
  ans="$(psql -U "$user" -d template1 -v ON_ERROR_STOP=1 -tAc \
    "SELECT CASE WHEN rolsuper THEN 'yes' ELSE 'no' END FROM pg_roles WHERE rolname = current_user" \
    2>/dev/null || true)"
  ans="$(printf '%s' "$ans" | tr -d '[:space:]')"
  [ "$ans" = "yes" ]
}

list_supers() {
  local user=$1
  psql -U "$user" -d template1 -v ON_ERROR_STOP=1 -tAc \
    "SELECT rolname FROM pg_roles WHERE rolsuper AND rolcanlogin ORDER BY rolname" \
    2>/dev/null || true
}

# Prints the superuser role name on stdout. Diagnostics go to stderr.
find_superuser() {
  local i=0 user candidate kind errfile announced=0 socket_down tried
  errfile="$(mktemp)"
  while [ "$i" -lt "$WAIT_SECS" ]; do
    socket_down=0
    tried=" "
    for user in postgres "$NETDISCO_DB_USER"; do
      [ -n "$user" ] || continue
      case "$tried" in
        *" $user "*) continue ;;
      esac
      tried="${tried}${user} "
      if try_connect "$user" "$errfile"; then
        if is_super "$user"; then
          rm -f "$errfile"
          printf '%s\n' "$user"
          return 0
        fi
        while IFS= read -r candidate; do
          candidate="$(printf '%s' "$candidate" | tr -d '[:space:]')"
          [ -n "$candidate" ] || continue
          [ "$candidate" = "$user" ] && continue
          if try_connect "$candidate" "$errfile"; then
            if is_super "$candidate"; then
              rm -f "$errfile"
              printf '%s\n' "$candidate"
              return 0
            fi
          else
            kind="$(err_kind "$errfile")"
            if [ "$kind" = "retry" ]; then
              socket_down=1
              break
            fi
            echo "psql -U ${candidate} failed; trying the next role" >&2
            redact < "$errfile" >&2
          fi
        done < <(list_supers "$user")
        if [ "$socket_down" = 1 ]; then
          break
        fi
        continue
      fi
      kind="$(err_kind "$errfile")"
      if [ "$kind" = "retry" ]; then
        socket_down=1
        if [ "$announced" = 0 ]; then
          echo "waiting for the postgres socket" >&2
          redact < "$errfile" >&2
          announced=1
        fi
        break
      fi
      echo "psql -U ${user} failed; trying the next role" >&2
      redact < "$errfile" >&2
    done
    if [ "$socket_down" = 0 ]; then
      echo "no superuser role accepted the local socket" >&2
      rm -f "$errfile"
      return 1
    fi
    i=$((i + 1))
    sleep "$SLEEP_SECS"
  done
  echo "postgres socket not available for the netdisco app role" >&2
  if [ -s "$errfile" ]; then
    redact < "$errfile" >&2
  fi
  rm -f "$errfile"
  return 1
}

align_role() {
  local super=$1
  # %I / %L quote the identifier and the password. psql does not echo the statement.
  # A superuser app role keeps rolsuper; only its password is changed.
  psql -U "$super" -d template1 -v ON_ERROR_STOP=1 \
    -v role="$NETDISCO_DB_USER" -v pass="$NETDISCO_DB_PASS" -v dbname="$NETDISCO_DB_NAME" <<'SQL'
SELECT format(
  'CREATE ROLE %I WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L',
  :'role', :'pass')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'role')
\gexec
SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L', :'role', :'pass')
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'role' AND rolsuper)
\gexec
SELECT format(
  'ALTER ROLE %I WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L',
  :'role', :'pass')
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'role' AND NOT rolsuper)
\gexec
SELECT format('CREATE DATABASE %I OWNER %I', :'dbname', :'role')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'dbname')
\gexec
SELECT format('ALTER DATABASE %I OWNER TO %I', :'dbname', :'role')
\gexec
SQL

  psql -U "$super" -d template1 -v ON_ERROR_STOP=1 \
    -v role="$NETDISCO_DB_USER" -v dbname="$NETDISCO_DB_NAME" <<'SQL'
SELECT format('GRANT ALL PRIVILEGES ON DATABASE %I TO %I', :'dbname', :'role')
\gexec
SQL
  echo "netdisco app role is aligned with NETDISCO_DB_USER/NETDISCO_DB_NAME via superuser ${super}" >&2
}

run_align() {
  : "${NETDISCO_DB_NAME:?}"
  : "${NETDISCO_DB_USER:?}"
  : "${NETDISCO_DB_PASS:?}"
  local super
  super="$(find_superuser)"
  align_role "$super"
}

self_test() {
  local tmp mock pass log err mode
  tmp="$(mktemp -d)"
  mock="$tmp/psql"
  pass='super-secret-pass'
  cat > "$mock" <<'EOF'
#!/bin/bash
printf '%s\n' "$*" >> "$MOCK_LOG"
user=""
query=""
prev=""
for a in "$@"; do
  if [ "$prev" = "-U" ]; then user=$a; fi
  if [ "$prev" = "-c" ] || [ "$prev" = "-tAc" ]; then query=$a; fi
  prev=$a
done
if [ -z "$query" ] && [ ! -t 0 ]; then
  echo "STDIN<<" >> "$MOCK_LOG"
  cat >> "$MOCK_LOG"
  echo ">>STDIN" >> "$MOCK_LOG"
fi
left=0
if [ -f "$MOCK_DIR/socket_left" ]; then
  left="$(cat "$MOCK_DIR/socket_left")"
fi
if [ "$left" -gt 0 ]; then
  echo $((left - 1)) > "$MOCK_DIR/socket_left"
  echo 'psql: error: connection to server on socket "/var/run/postgresql/.s.PGSQL.5432" failed: No such file or directory' >&2
  echo 'Is the server running locally and accepting connections on that socket?' >&2
  exit 2
fi
answer() {
  case "$query" in
    *"rolsuper AND rolcanlogin"*) printf '%s\n' "$1" ;;
    *rolsuper*) printf '%s\n' "$2" ;;
  esac
}
case "$MOCK_MODE" in
  postgres-super|socket-then-postgres)
    if [ "$user" != "postgres" ]; then
      echo "FATAL: role \"$user\" does not exist" >&2
      exit 2
    fi
    answer postgres yes
    exit 0
    ;;
  netdisco-super)
    if [ "$user" = "postgres" ]; then
      echo 'FATAL: role "postgres" does not exist' >&2
      exit 2
    fi
    if [ "$user" != "netdisco" ]; then
      echo "FATAL: role \"$user\" does not exist" >&2
      exit 2
    fi
    answer netdisco yes
    exit 0
    ;;
  other-super)
    if [ "$user" = "postgres" ]; then
      answer clusteradmin no
      exit 0
    fi
    if [ "$user" = "clusteradmin" ]; then
      answer clusteradmin yes
      exit 0
    fi
    echo "password authentication failed for user \"$user\"" >&2
    exit 2
    ;;
  *)
    echo "mock psql: unknown mode $MOCK_MODE" >&2
    exit 2
    ;;
esac
EOF
  chmod +x "$mock"

  run_mode() {
    mode=$1
    log="$tmp/${mode}.log"
    err="$tmp/${mode}.err"
    : > "$log"
    printf '%s\n' "${2:-0}" > "$tmp/socket_left"
    env \
      PATH="$tmp:$PATH" \
      MOCK_LOG="$log" \
      MOCK_DIR="$tmp" \
      MOCK_MODE="$mode" \
      NETDISCO_DB_NAME=netdisco \
      NETDISCO_DB_USER=netdisco \
      NETDISCO_DB_PASS="$pass" \
      NETDISCO_ROLE_WAIT=5 \
      NETDISCO_ROLE_SLEEP=0 \
      bash "$0" >"$tmp/${mode}.out" 2>"$err"
  }

  run_mode postgres-super 0
  grep -q 'via superuser postgres' "$tmp/postgres-super.err"
  grep -q -- '-U postgres' "$tmp/postgres-super.log"
  grep -q 'AND rolsuper' "$tmp/postgres-super.log"
  grep -q 'AND NOT rolsuper' "$tmp/postgres-super.log"
  if grep -q -- '-U netdisco -d template1 -v ON_ERROR_STOP=1 -v role=' "$tmp/postgres-super.log"; then
    echo "postgres-super cluster aligned as the app role" >&2
    exit 1
  fi

  run_mode netdisco-super 0
  grep -q 'role "postgres" does not exist' "$tmp/netdisco-super.err"
  grep -q 'via superuser netdisco' "$tmp/netdisco-super.err"
  grep -q -- '-U netdisco -d template1 -v ON_ERROR_STOP=1 -v role=' "$tmp/netdisco-super.log"
  if grep -F -q "$pass" "$tmp/netdisco-super.err"; then
    echo "password leaked into the netdisco-super error output" >&2
    exit 1
  fi

  run_mode other-super 0
  grep -q 'via superuser clusteradmin' "$tmp/other-super.err"
  grep -q -- '-U clusteradmin' "$tmp/other-super.log"

  run_mode socket-then-postgres 2
  grep -q 'No such file or directory' "$tmp/socket-then-postgres.err"
  grep -q 'via superuser postgres' "$tmp/socket-then-postgres.err"
  if grep -F -q "$pass" "$tmp/socket-then-postgres.err" \
    || grep -F -q "$pass" "$tmp/postgres-super.err" \
    || grep -F -q "$pass" "$tmp/other-super.err"; then
    echo "password leaked into an error stream" >&2
    exit 1
  fi

  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    echo "NOTE  docker daemon is available; both cluster shapes were simulated with a mock psql (no postgres image was started)"
  else
    echo "SKIP  live postgres clusters: docker daemon is not available. Both cluster shapes (superuser postgres, and superuser netdisco with no postgres role) were simulated with a mock psql."
  fi
  rm -rf "$tmp"
  echo "PASS  netdisco role aligner finds postgres, netdisco, or another superuser and does not demote a superuser app role"
}

if [ "${1:-}" = "--self-test" ]; then
  self_test
  exit 0
fi

run_align
