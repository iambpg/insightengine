#!/usr/bin/env bash
# install.sh --upgrade-env accepts a pre-marker InsightEngine .env and refuses
# anything else. A plain ./install.sh still refuses a .env that has no marker.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

fail() { printf 'FAIL %s\n' "$*" >&2; exit 1; }

prepare() {
  local dir
  dir="$(mktemp -d)"
  cp "$ROOT/install.sh" "$dir/install.sh"
  cp "$ROOT/.env.example" "$dir/.env.example"
  chmod +x "$dir/install.sh"
  printf '%s' "$dir"
}

write_real_env() {
  local dir=$1 filter=${2:-status=active}
  cat > "$dir/.env" <<EOF
CLIENT_NAME='Acme'
CLIENT_SLUG='acme'
INSTALL_DIR='/opt/insightengine'
PUBLIC_HOST='monitor.example'
PORT_HTTP=8080
PORT_HTTPS=8443
NETBOX_DB_PASSWORD='keep-db'
NETBOX_SECRET_KEY='keep-secret-key'
NETBOX_SUPERUSER_API_TOKEN='keep-token-value'
NETBOX_REDIS_PASSWORD=
OXIDIZED_NETBOX_FILTER='${filter}'
EOF
}

env_val() {
  local file=$1 key=$2 line
  line="$(grep -E "^${key}=" "$file" | tail -n1 || true)"
  line="${line#*=}"
  line="${line#\'}"
  line="${line%\'}"
  printf '%s' "$line"
}

assert_identity_unchanged() {
  local env=$1
  [ "$(env_val "$env" CLIENT_NAME)" = "Acme" ] || fail "CLIENT_NAME changed"
  [ "$(env_val "$env" CLIENT_SLUG)" = "acme" ] || fail "CLIENT_SLUG changed"
  [ "$(env_val "$env" INSTALL_DIR)" = "/opt/insightengine" ] || fail "INSTALL_DIR changed"
  [ "$(env_val "$env" PUBLIC_HOST)" = "monitor.example" ] || fail "PUBLIC_HOST changed"
  [ "$(env_val "$env" PORT_HTTP)" = "8086" ] || fail "PORT_HTTP was not moved off 8080"
  [ "$(env_val "$env" PORT_HTTPS)" = "8443" ] || fail "PORT_HTTPS changed"
  [ "$(env_val "$env" PORT_NETBOX)" = "8080" ] || fail "missing PORT_NETBOX was not set to 8080"
  [ "$(env_val "$env" NETBOX_DB_PASSWORD)" = "keep-db" ] || fail "NETBOX_DB_PASSWORD replaced"
  [ "$(env_val "$env" NETBOX_SECRET_KEY)" = "keep-secret-key" ] || fail "NETBOX_SECRET_KEY replaced"
  [ "$(env_val "$env" NETBOX_SUPERUSER_API_TOKEN)" = "keep-token-value" ] || fail "API token replaced"
}

assert_certs_unchanged() {
  local dir=$1
  [ "$(cat "$dir/certs/ca.crt")" = "original-ca" ] || fail "ca.crt regenerated"
  [ "$(cat "$dir/certs/server.crt")" = "original-crt" ] || fail "server.crt regenerated"
  [ "$(cat "$dir/certs/server.key")" = "original-key" ] || fail "server.key regenerated"
}

seed_certs() {
  local dir=$1
  mkdir -p "$dir/certs"
  printf 'original-ca' > "$dir/certs/ca.crt"
  printf 'original-crt' > "$dir/certs/server.crt"
  printf 'original-key' > "$dir/certs/server.key"
}

run_install() {
  local dir=$1
  shift
  local out rc
  set +e
  out="$(cd "$dir" && ./install.sh "$@" 2>&1)"
  rc=$?
  set -e
  printf '%s\n' "$out"
  return "$rc"
}

# Plain install.sh refuses a pre-marker .env and writes nothing.
dir="$(prepare)"
write_real_env "$dir"
seed_certs "$dir"
before="$(cksum "$dir/.env")"
set +e
refused="$(run_install "$dir" --no-start)"
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "plain install.sh accepted a pre-marker .env"
printf '%s\n' "$refused" | grep -q 'already exists' || fail "plain install.sh did not report the existing .env"
[ ! -e "$dir/.install-started" ] || fail "plain install.sh wrote .install-started"
[ "$(cksum "$dir/.env")" = "$before" ] || fail "plain install.sh modified .env"
assert_certs_unchanged "$dir"
rm -rf "$dir"

# --upgrade-env fills only empty secrets, writes the marker afterwards, and
# leaves identity, existing secrets, and certificates alone.
dir="$(prepare)"
write_real_env "$dir" 'status=active&tag=oxidized'
seed_certs "$dir"
if ! (cd "$dir" && ./install.sh --upgrade-env --no-start >"$dir/out" 2>&1); then
  cat "$dir/out" >&2
  fail "upgrade-env failed"
fi
grep -qx 'past-secret-generation' "$dir/.install-started" || fail "marker missing after upgrade"
grep -q 'set PORT_HTTP=8086 (was 8080)' "$dir/out" || fail "upgrade did not say HTTP moved off 8080"
grep -q 'PORT_HTTPS stays 8443' "$dir/out" || fail "upgrade did not leave the non-default HTTPS port"
grep -q 'Open host port 8086' "$dir/out" || fail "upgrade did not say to open 8086"
assert_identity_unchanged "$dir/.env"
assert_certs_unchanged "$dir"
[ "$(env_val "$dir/.env" OXIDIZED_NETBOX_FILTER)" = "status=active" ] || fail "old oxidized filter was kept"
added="$(env_val "$dir/.env" NETBOX_SUPERUSER_API_KEY)"
[ -n "$added" ] || fail "NETBOX_SUPERUSER_API_KEY was not backfilled"
redis="$(env_val "$dir/.env" NETBOX_REDIS_PASSWORD)"
[ -n "$redis" ] || fail "empty NETBOX_REDIS_PASSWORD was not backfilled"
[ "$added" != "keep-db" ] || fail "backfill copied an existing secret"
# --backfill-env is the same flag and must not replace the values just written.
if ! (cd "$dir" && ./install.sh --backfill-env --no-start >"$dir/out" 2>&1); then
  cat "$dir/out" >&2
  fail "second backfill failed"
fi
[ "$(env_val "$dir/.env" NETBOX_SUPERUSER_API_KEY)" = "$added" ] || fail "second backfill replaced the API key"
[ "$(env_val "$dir/.env" NETBOX_DB_PASSWORD)" = "keep-db" ] || fail "second backfill replaced the db password"
rm -rf "$dir"

# Dry-run shows the pre-marker path and writes nothing.
dir="$(prepare)"
write_real_env "$dir"
seed_certs "$dir"
before="$(cksum "$dir/.env")"
set +e
preview="$(run_install "$dir" --upgrade-env --no-start --dry-run)"
rc=$?
set -e
[ "$rc" -eq 0 ] || fail "dry-run refused a real pre-marker .env: $preview"
printf '%s\n' "$preview" | grep -q 'pre-marker .env accepted' || fail "dry-run did not say it would accept the pre-marker .env"
printf '%s\n' "$preview" | grep -q 'would write .install-started after backfill' || fail "dry-run did not show the marker write"
printf '%s\n' "$preview" | grep -q 'would add NETBOX_SUPERUSER_API_KEY' || fail "dry-run did not list the missing API key"
printf '%s\n' "$preview" | grep -q 'would leave PUBLIC_HOST' || fail "dry-run did not say identity stays"
printf '%s\n' "$preview" | grep -q 'would set PORT_HTTP=8086' || fail "dry-run did not preview the HTTP port move"
if printf '%s\n' "$preview" | grep -q 'would add NETBOX_DB_PASSWORD'; then
  fail "dry-run listed a secret that already has a value"
fi
[ "$(cksum "$dir/.env")" = "$before" ] || fail "dry-run modified .env"
[ ! -e "$dir/.install-started" ] || fail "dry-run wrote .install-started"
assert_certs_unchanged "$dir"
rm -rf "$dir"

refuse_corrupt() {
  local label=$1 dir=$2
  before="$(cksum "$dir/.env")"
  set +e
  out="$(run_install "$dir" --upgrade-env --no-start)"
  rc=$?
  set -e
  [ "$rc" -ne 0 ] || fail "$label was accepted"
  printf '%s\n' "$out" | grep -q 'refusing --upgrade-env' || fail "$label was not refused: $out"
  [ ! -e "$dir/.install-started" ] || fail "$label wrote .install-started"
  [ "$(cksum "$dir/.env")" = "$before" ] || fail "$label modified .env"
  rm -rf "$dir"
}

dir="$(prepare)"
write_real_env "$dir"
sed -i '/^PUBLIC_HOST=/d' "$dir/.env"
refuse_corrupt "env missing PUBLIC_HOST" "$dir"

dir="$(prepare)"
write_real_env "$dir"
sed -i "s|^INSTALL_DIR=.*|INSTALL_DIR=|" "$dir/.env"
refuse_corrupt "env with empty INSTALL_DIR" "$dir"

dir="$(prepare)"
printf '%s\n' 'FOO=bar' 'PUBLIC_HOST=monitor.example' > "$dir/.env"
refuse_corrupt "partial env" "$dir"

dir="$(prepare)"
write_real_env "$dir"
sed -i "s|^PUBLIC_HOST=.*|PUBLIC_HOST='not a host'|" "$dir/.env"
refuse_corrupt "env with a bad PUBLIC_HOST" "$dir"

# A real old default moves. A chosen alternate (19090, 57400) stays.
dir="$(prepare)"
cat > "$dir/.env" <<'EOF'
CLIENT_NAME='Acme'
CLIENT_SLUG='acme'
INSTALL_DIR='/opt/insightengine'
PUBLIC_HOST='monitor.example'
PORT_HTTP=80
PORT_HTTPS=57400
PORT_NETBOX=8444
PORT_PROMETHEUS=19090
NETBOX_DB_PASSWORD='keep-db'
NETBOX_SECRET_KEY='keep-secret-key'
EOF
seed_certs "$dir"
if ! (cd "$dir" && ./install.sh --upgrade-env --no-start >"$dir/out" 2>&1); then
  cat "$dir/out" >&2
  fail "default-port upgrade failed"
fi
[ "$(env_val "$dir/.env" PORT_HTTP)" = "8086" ] || fail "old HTTP default 80 was not moved"
[ "$(env_val "$dir/.env" PORT_NETBOX)" = "8080" ] || fail "old NetBox default 8444 was not moved"
[ "$(env_val "$dir/.env" PORT_HTTPS)" = "57400" ] || fail "configured HTTPS 57400 was moved"
[ "$(env_val "$dir/.env" PORT_PROMETHEUS)" = "19090" ] || fail "alternate Prometheus port was rewritten"
[ "$(env_val "$dir/.env" PORT_HTTP3)" = "443" ] || fail "PORT_HTTP3 was not added"
[ "$(env_val "$dir/.env" PORT_SNMP_EXPORTER)" = "9116" ] || fail "PORT_SNMP_EXPORTER was not added"
[ "$(env_val "$dir/.env" PORT_BLACKBOX)" = "9115" ] || fail "PORT_BLACKBOX was not added"
[ "$(env_val "$dir/.env" PORT_TELEGRAF)" = "57500" ] || fail "PORT_TELEGRAF was not added"
grep -q 'left PORT_PROMETHEUS=19090' "$dir/out" || fail "did not name the firewall port for Prometheus"
grep -q 'PORT_HTTPS stays 57400' "$dir/out" || fail "did not say HTTPS stays 57400"
grep -q 'Open host port 8080' "$dir/out" || fail "did not say to open NetBox 8080"
rm -rf "$dir"

echo "PASS  pre-marker .env is upgraded only with --upgrade-env; corrupt .env is refused"
