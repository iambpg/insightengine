#!/usr/bin/env bash
# Prove netbox-postgres and insightengine-postgres keep a row across
# `docker compose down` and `up -d`. Uses its own compose project name and
# client slug so it does not attach to a real install's volumes.
#
#   ./scripts/test-pg-persistence.sh
# Skips with exit 0 when docker is not available.
set -euo pipefail
umask 077
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ "${1:-}" = "--self-test" ]; then
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  SUBNET="10.254.40.0/24"
  sed -E \
    "s|^(CLIENT_SLUG)=.*|\1='iepgtest'|; s|^MONITORING_SUBNET=.*|MONITORING_SUBNET=${SUBNET}|; s#^INSTALL_DIR=.*#INSTALL_DIR='${ROOT}'#" \
    .env.example > "$tmp/env"
  grep -q "^MONITORING_SUBNET=${SUBNET}$" "$tmp/env"
  grep -q "^INSTALL_DIR='${ROOT}'$" "$tmp/env"
  printf '%s\n' \
    "NETBOX_DB_PASSWORD=old|value" \
    "GRAFANA_SECRET_KEY=old" \
    "NETBOX_API_TOKEN_PEPPER_1=old" \
    "NETBOX_SUPERUSER_API_TOKEN=old" \
    "NETBOX_SUPERUSER_API_KEY=old" \
    "AP_ENCRYPTION_KEY=old" \
    "AP_JWT_SECRET=old" \
    "CLIENT_NAME=keep" \
    > "$tmp/in"
  sed -E \
    "s#^([A-Z0-9_]*(PASSWORD|SECRET_KEY|PEPPER_1|API_TOKEN|API_KEY|ENCRYPTION_KEY|JWT_SECRET))=.*#\1='persist-test-secret'#" \
    "$tmp/in" > "$tmp/secrets"
  for key in NETBOX_DB_PASSWORD GRAFANA_SECRET_KEY NETBOX_API_TOKEN_PEPPER_1 \
    NETBOX_SUPERUSER_API_TOKEN NETBOX_SUPERUSER_API_KEY AP_ENCRYPTION_KEY AP_JWT_SECRET; do
    grep -qx "${key}='persist-test-secret'" "$tmp/secrets"
  done
  grep -qx "CLIENT_NAME=keep" "$tmp/secrets"
  echo "PASS  persistence env sed accepts a subnet containing / and a secrets alternation containing |"
  exit 0
fi

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  echo "SKIP  postgres persistence (docker compose is not available)"
  exit 0
fi
if ! docker info >/dev/null 2>&1; then
  echo "SKIP  postgres persistence (docker daemon is not running)"
  exit 0
fi

PROJECT="iepgpersist$$"
SLUG="iepgtest$$"
TMP="$(mktemp -d)"
CREATED_SECRETS=()
cleanup() {
  docker compose --project-name "$PROJECT" --env-file "$TMP/env" down -v --remove-orphans >/dev/null 2>&1 || true
  local f
  for f in "${CREATED_SECRETS[@]:-}"; do
    rm -f "$f"
  done
  rm -rf "$TMP"
}
trap cleanup EXIT

touch_secret() {
  local path=$1
  if [ ! -e "$path" ]; then
    mkdir -p "$(dirname "$path")"
    printf 'x' > "$path"
    CREATED_SECRETS+=("$path")
  fi
}

# A distinct subnet so this project does not collide with a stack already using 10.50.0.0/24.
SUBNET="10.254.$(( ($$ % 200) + 20 )).0/24"
# compose interpolates the whole file, including services this test does not start.
sed -E \
  "s|^(CLIENT_NAME)=.*|\1='PG Persist'|; s|^(CLIENT_SLUG)=.*|\1='${SLUG}'|; s|^(PUBLIC_HOST)=.*|\1='127.0.0.1'|; s|^MONITORING_SUBNET=.*|MONITORING_SUBNET=${SUBNET}|; s#^([A-Z0-9_]*(PASSWORD|SECRET_KEY|PEPPER_1|API_TOKEN|API_KEY|ENCRYPTION_KEY|JWT_SECRET))=.*#\1='persist-test-secret'#; s|^ADMIN_BASIC_HASH=.*|ADMIN_BASIC_HASH='x'|; s#^INSTALL_DIR=.*#INSTALL_DIR='${ROOT}'#" \
  .env.example > "$TMP/env"
echo "using subnet ${SUBNET}"

for rel in \
  secrets/prometheus/netbox.token \
  secrets/oxidized/netbox.token \
  secrets/oxidized/device_username \
  secrets/oxidized/device_password \
  secrets/trapd/trap_community \
  secrets/trapd/v3_users.conf \
  secrets/telegraf/fortigate_token \
  secrets/telegraf/panos_api_key \
  secrets/telegraf/ise_credentials \
  secrets/telegraf/dnac_credentials \
  secrets/telegraf/sdwan_credentials \
  secrets/cust-exporter/netbox.token \
  secrets/setup/token
do
  touch_secret "$rel"
done
mkdir -p certs data/netdisco/logs cust-exporter/app
[ -f certs/ca.crt ] || touch_secret certs/ca.crt
[ -f certs/server.crt ] || touch_secret certs/server.crt
[ -f certs/server.key ] || touch_secret certs/server.key

compose() {
  docker compose --project-name "$PROJECT" --env-file "$TMP/env" "$@"
}

echo "starting postgres services in project ${PROJECT}"
compose up -d netbox-postgres insightengine-postgres

wait_healthy() {
  local name=$1
  local _try
  for _try in $(seq 1 60); do
    state="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$name" 2>/dev/null || true)"
    if [ "$state" = "healthy" ]; then
      return 0
    fi
    sleep 2
  done
  echo "FAIL  ${name} did not become healthy" >&2
  docker logs "$name" 2>&1 | tail -n 40 >&2 || true
  exit 1
}

wait_healthy "netbox-postgres-${SLUG}"
wait_healthy "insightengine-postgres-${SLUG}"

marker() {
  local container=$1 db=$2 user=$3
  docker exec -e PGPASSWORD=persist-test-secret "$container" \
    psql -v ON_ERROR_STOP=1 -U "$user" -d "$db" \
    -c "CREATE TABLE IF NOT EXISTS ie_persist_marker (id int primary key, note text); INSERT INTO ie_persist_marker (id, note) VALUES (1, 'kept') ON CONFLICT (id) DO UPDATE SET note = 'kept';"
}

check_marker() {
  local container=$1 db=$2 user=$3
  docker exec -e PGPASSWORD=persist-test-secret "$container" \
    psql -v ON_ERROR_STOP=1 -U "$user" -d "$db" -tA \
    -c "SELECT note FROM ie_persist_marker WHERE id = 1;"
}

marker "netbox-postgres-${SLUG}" netbox netbox
marker "insightengine-postgres-${SLUG}" insightengine insightengine

echo "stopping the project without deleting volumes"
compose down

echo "starting again"
compose up -d netbox-postgres insightengine-postgres
wait_healthy "netbox-postgres-${SLUG}"
wait_healthy "insightengine-postgres-${SLUG}"

nb="$(check_marker "netbox-postgres-${SLUG}" netbox netbox | tr -d '[:space:]')"
ie="$(check_marker "insightengine-postgres-${SLUG}" insightengine insightengine | tr -d '[:space:]')"
if [ "$nb" != "kept" ] || [ "$ie" != "kept" ]; then
  echo "FAIL  marker did not survive down/up (netbox='${nb}' insightengine='${ie}')" >&2
  exit 1
fi
echo "PASS  postgres rows survived docker compose down && up -d"
