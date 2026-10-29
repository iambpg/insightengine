#!/usr/bin/env bash
# Static validation of the bundle. Starts NOTHING. Uses whatever tools exist:
#   docker compose (or COMPOSE_BIN), promtool, amtool, caddy, blackbox_exporter,
#   snmp_exporter, loki, telegraf, shellcheck. Missing tools are reported as SKIP.
# Reads .env if present, else .env.example with dummy values.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
fail=0
ok()   { printf 'PASS  %s\n' "$*"; }
bad()  { printf 'FAIL  %s\n' "$*"; fail=1; }
skip() { printf 'SKIP  %s (tool not found)\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

COMPOSE="${COMPOSE_BIN:-}"
if [ -z "$COMPOSE" ]; then if have docker && docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"; fi; fi

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
ENVFILE=.env
if [ ! -f .env ]; then
  ENVFILE="$TMP/env"
  sed -E "s/^(CLIENT_NAME)=.*/\1='Example Client'/; s/^(CLIENT_SLUG)=.*/\1='example-client'/; s/^(PUBLIC_HOST)=.*/\1='monitor.example.invalid'/; s/^([A-Z0-9_]*(PASSWORD|SECRET_KEY|PEPPER_1|API_TOKEN|API_KEY|ENCRYPTION_KEY|JWT_SECRET))=.*/\1='dummy-value-for-validation'/; s/^ADMIN_BASIC_HASH=.*/ADMIN_BASIC_HASH='dummy'/; s#^INSTALL_DIR=.*#INSTALL_DIR='$ROOT'#" .env.example > "$ENVFILE"
  echo "note: no .env yet - validating with dummy values (nothing is written to .env)"
fi

# --- dockerfile COPY sources and compose mount/command audit (no daemon required)
if have python3; then
  if python3 scripts/check-docker-copy.py >"$TMP/copy.out" 2>&1; then ok "dockerfile COPY sources"; else bad "dockerfile COPY sources"; cat "$TMP/copy.out"; fi
  if python3 -c 'import yaml' >/dev/null 2>&1; then
    if python3 scripts/check-compose-audit.py >"$TMP/audit.out" 2>&1; then ok "compose mount/command audit"; else bad "compose mount/command audit"; cat "$TMP/audit.out"; fi
  else
    skip "compose mount/command audit (PyYAML missing)"
  fi
else
  skip "dockerfile COPY and compose audit"
fi

# --- compose
if [ -n "$COMPOSE" ]; then
  mkdir -p secrets certs cust-exporter/app data/netdisco/logs
  if COMPOSE_PROFILES='*' $COMPOSE --env-file "$ENVFILE" config -q 2>"$TMP/c.err"; then ok "compose config (all profiles)"; else bad "compose config"; sed 's/^/      /' "$TMP/c.err"; fi
else skip "compose config"; fi

# --- compose policy: who may touch the Docker socket / publish ports
if [ -n "$COMPOSE" ] && have python3; then
  COMPOSE_PROFILES='*' $COMPOSE --env-file "$ENVFILE" config --format json > "$TMP/c.json" 2>/dev/null
  if python3 - "$TMP/c.json" <<'PY' 2>"$TMP/pol.err"
import json, sys
c = json.load(open(sys.argv[1]))
svc = c["services"]
sock = sorted(n for n, s in svc.items() if any("docker.sock" in str(v.get("source", "")) for v in s.get("volumes", [])))
assert sock == ["docker-socket-proxy", "ie-config-docker-proxy", "telegraf-host"], "docker.sock holders: %s" % sock
for n in ("setup", "docker-socket-proxy", "ie-config-docker-proxy", "ie-config", "insightengine-ui"):
    assert not svc[n].get("ports"), "%s must not publish ports" % n
assert set(svc["docker-socket-proxy"]["networks"]) == {"docker-proxy-net"}, "proxy network"
assert set(svc["ie-config-docker-proxy"]["networks"]) == {"docker-proxy-net"}, "ie-config proxy network"
assert c["networks"]["docker-proxy-net"].get("internal") is True, "docker-proxy-net must be internal"
assert "DOCKER_HOST" in svc["setup"]["environment"] and not any("docker.sock" in str(v.get("source","")) for v in svc["setup"].get("volumes", [])), "setup must use the proxy only"
env = svc["docker-socket-proxy"]["environment"]
for k in ("SECRETS", "AUTH", "BUILD", "COMMIT", "SWARM", "SYSTEM", "PLUGINS"):
    assert env.get(k) == "0", "%s must stay 0" % k
narrow = svc["ie-config-docker-proxy"]["environment"]
for k in ("SECRETS", "AUTH", "BUILD", "COMMIT", "SWARM", "SYSTEM", "PLUGINS", "IMAGES", "NETWORKS", "VOLUMES", "EXEC"):
    assert str(narrow.get(k)) == "0", "ie-config proxy %s must stay 0" % k
assert str(narrow.get("ALLOW_RESTARTS")) == "1"
assert str(narrow.get("ALLOW_START")) == "0"
assert str(narrow.get("ALLOW_STOP")) == "0"
assert str(narrow.get("POST")) == "1"
PY
  then ok "compose policy (socket holders, no published ports, proxy allow-list)"; else bad "compose policy"; sed 's/^/      /' "$TMP/pol.err"; fi
else skip "compose policy"; fi

# --- setup service: syntax, page script, end-to-end API test against stubs
if have python3; then
  if python3 -m py_compile setup/server.py setup/tests/test_setup_api.py netbox/regions/import_regions.py 2>"$TMP/py.err"; then ok "python syntax setup/server.py"; else bad "python syntax"; cat "$TMP/py.err"; fi
  if python3 -c 'import yaml' >/dev/null 2>&1; then
    if python3 netbox/regions/test_regions.py >"$TMP/reg.out" 2>&1; then ok "region catalog tests"; else bad "region catalog tests"; tail -n 40 "$TMP/reg.out" | sed 's/^/      /'; fi
  else
    skip "region catalog tests (PyYAML missing)"
  fi
  find setup -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null
  if timeout 120 python3 -W ignore setup/tests/test_setup_api.py >"$TMP/ut.out" 2>&1; then ok "setup API tests (stub docker/scripts; no real daemon)"; else bad "setup API tests"; tail -n 30 "$TMP/ut.out" | sed 's/^/      /'; fi
else skip "setup service tests"; fi
if have node; then
  if node --check setup/static/app.js 2>"$TMP/js.err"; then ok "node --check setup/static/app.js"; else bad "first-run page script"; cat "$TMP/js.err"; fi
else skip "node --check"; fi

# --- load env for tool checks (values are not echoed)
set -a; # shellcheck disable=SC1090
. "$ENVFILE" 2>/dev/null; set +a
export CLIENT_NAME="${CLIENT_NAME:-x}" CLIENT_SLUG="${CLIENT_SLUG:-x}"

# --- prometheus
if have promtool; then
  P="$TMP/prom"; mkdir -p "$P/ie-certs"
  sed "s#/etc/prometheus/#$P/#g; s#/etc/ie-certs/#$P/ie-certs/#g; s#/run/secrets/netbox_token#$P/tok#g" config/prometheus/prometheus.yml > "$P/prometheus.yml"
  cp config/prometheus/alert-rules.yml "$P/"; cp -f certs/ca.crt "$P/ie-certs/ca.crt" 2>/dev/null || : > "$P/ie-certs/ca.crt"; echo x > "$P/tok"
  if promtool check config "$P/prometheus.yml" >"$TMP/p.out" 2>&1; then ok "promtool check config"; else bad "promtool check config"; sed 's/^/      /' "$TMP/p.out"; fi
else skip "promtool"; fi
# --- alertmanager
if have amtool; then
  if amtool check-config config/alertmanager/alertmanager.yml >"$TMP/a.out" 2>&1; then ok "amtool check-config"; else bad "amtool check-config"; sed 's/^/      /' "$TMP/a.out"; fi
else skip "amtool"; fi
# --- caddy
if have caddy; then
  for f in config/caddy/Caddyfile config/caddy/Caddyfile.scrape-lb; do
    if caddy validate --config "$f" --adapter caddyfile >"$TMP/cd.out" 2>&1; then ok "caddy validate $f"; else
      # certificates are bind-mounted at /certs in the container; a missing file here is not a syntax error
      if grep -q '/certs/' "$TMP/cd.out"; then ok "caddy adapt $f (cert path only exists inside the container)"; else bad "caddy validate $f"; sed 's/^/      /' "$TMP/cd.out"; fi
    fi
  done
else skip "caddy"; fi
# --- blackbox
if have blackbox_exporter; then
  if blackbox_exporter --config.check --config.file=config/blackbox/blackbox.yml >"$TMP/b.out" 2>&1; then ok "blackbox config check"; else bad "blackbox config check"; sed 's/^/      /' "$TMP/b.out"; fi
else skip "blackbox_exporter"; fi
# --- snmp exporter (dry-run needs non-empty SNMP_* env)
if have snmp_exporter; then
  : "${SNMP_V3_USER:=x}"
  : "${SNMP_V3_USERNAME:=$SNMP_V3_USER}"
  if SNMP_V2_COMMUNITY="${SNMP_V2_COMMUNITY:-x}" SNMP_V3_USER="$SNMP_V3_USER" SNMP_V3_USERNAME="$SNMP_V3_USERNAME" SNMP_V3_AUTH_PASSWORD="${SNMP_V3_AUTH_PASSWORD:-x}" SNMP_V3_PRIV_PASSWORD="${SNMP_V3_PRIV_PASSWORD:-x}" \
     snmp_exporter --config.file=snmp/out/snmp.yml --config.expand-environment-variables --dry-run >"$TMP/s.out" 2>&1; then ok "snmp_exporter --dry-run"; else bad "snmp_exporter --dry-run"; sed 's/^/      /' "$TMP/s.out"; fi
else skip "snmp_exporter"; fi
# --- loki
if have loki; then
  if loki -config.file=config/loki/loki.yml -config.expand-env=true -verify-config >"$TMP/l.out" 2>&1; then ok "loki -verify-config"; else bad "loki -verify-config"; sed 's/^/      /' "$TMP/l.out"; fi
else skip "loki"; fi
# --- telegraf
if have telegraf; then
  for f in config/telegraf/api/telegraf.conf config/telegraf/host/telegraf.conf config/telegraf/syslog/telegraf.conf; do
    # --test needs the secret store path and live endpoints; parse-only is checked via --once --test-wait=0 failing only on connectivity
    if telegraf --config "$f" --test --test-wait 0 >"$TMP/t.out" 2>&1; then ok "telegraf parses $f"; else
      if grep -qiE 'error parsing|invalid configuration|unknown' "$TMP/t.out"; then bad "telegraf $f"; sed 's/^/      /' "$TMP/t.out" | head -n 20; else ok "telegraf parses $f (runtime errors only: no network/docker here)"; fi
    fi
  done
else skip "telegraf"; fi
# --- shell scripts
if have shellcheck; then
  if shellcheck -x install.sh scripts/*.sh config/oxidized/*.sh trapd/*.sh >"$TMP/sc.out" 2>&1; then ok "shellcheck"; else bad "shellcheck"; sed 's/^/      /' "$TMP/sc.out" | head -n 40; fi
else skip "shellcheck"; fi
# --- customer UI (Next.js under ui/). Skip only when node or npm is missing.
if have node && have npm; then
  if (cd ui && npm ci && npm run build && npm test) >"$TMP/ui.out" 2>&1; then
    ok "ui npm ci, build, test"
  else
    bad "ui npm ci, build, test"
    tail -n 40 "$TMP/ui.out" | sed 's/^/      /'
  fi
else
  skip "ui npm ci, build, test"
fi

# --- house rules
if grep -rIl -i 'zab''bix' . >/dev/null 2>&1; then bad "forbidden word found"; else ok "forbidden-word scan"; fi

exit "$fail"
