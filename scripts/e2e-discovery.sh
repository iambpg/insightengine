#!/usr/bin/env bash
# Smoke test for NetBox -> Prometheus and NetBox prefix -> Netdisco.
# This script was NOT run against real devices. A fake address will not answer ICMP.
# Target presence in Prometheus is the check. The `up` metric is printed and is not a failure
# unless IE_E2E_REQUIRE_UP=1.
set -euo pipefail
umask 077
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[ -f .env ] || { echo "no .env - run ./install.sh and finish /setup/ first" >&2; exit 1; }

envval() { local l; l="$(grep -E "^$1=" .env | head -n1 || true)"; l="${l#*=}"; l="${l#\'}"; l="${l%\'}"; printf '%s' "$l"; }
PUBLIC_HOST="$(envval PUBLIC_HOST)"
PORT_NETBOX="$(envval PORT_NETBOX)"; PORT_NETBOX="${PORT_NETBOX:-8444}"
PORT_PROMETHEUS="$(envval PORT_PROMETHEUS)"; PORT_PROMETHEUS="${PORT_PROMETHEUS:-9090}"
SLUG="$(envval CLIENT_SLUG)"
if [ -z "$SLUG" ] || [ "$SLUG" = unconfigured ]; then echo "finish first-run setup first" >&2; exit 1; fi

# shellcheck disable=SC1091
. "$(dirname "$0")/lib-netbox-auth.sh"
hdr="$(mktemp)"; trap 'rm -f "$hdr"' EXIT
netbox_write_auth_header "$hdr" || { echo "no NetBox token" >&2; exit 1; }

NB="https://${PUBLIC_HOST}:${PORT_NETBOX}"
nb() { # METHOD PATH [json]
  if [ -n "${3:-}" ]; then
    curl -fsS --cacert certs/ca.crt --resolve "${PUBLIC_HOST}:${PORT_NETBOX}:127.0.0.1" \
      -H @"$hdr" -H 'Content-Type: application/json' -H 'Accept: application/json' -X "$1" "$NB$2" -d "$3"
  else
    curl -fsS --cacert certs/ca.crt --resolve "${PUBLIC_HOST}:${PORT_NETBOX}:127.0.0.1" \
      -H @"$hdr" -H 'Accept: application/json' -X "$1" "$NB$2"
  fi
}

SITE="${IE_E2E_SITE:-e2e-site}"
DEV="${IE_E2E_DEVICE:-e2e-switch-1}"
IP="${IE_E2E_IP:-203.0.113.10}"
PREFIX="${IE_E2E_PREFIX:-203.0.113.0/24}"

echo "creating site, role, device and prefix in NetBox (addresses are documentation range TEST-NET-3)"
nb POST /api/dcim/sites/ "{\"name\":\"E2E Site\",\"slug\":\"${SITE}\",\"status\":\"active\"}" >/dev/null || true
nb POST /api/dcim/device-roles/ "{\"name\":\"Access Switch\",\"slug\":\"access-switch\",\"color\":\"2196f3\"}" >/dev/null || true
nb POST /api/dcim/manufacturers/ "{\"name\":\"Cisco\",\"slug\":\"cisco\"}" >/dev/null || true
nb POST /api/dcim/device-types/ "{\"manufacturer\":{\"slug\":\"cisco\"},\"model\":\"E2E Model\",\"slug\":\"e2e-model\"}" >/dev/null || true
# tag ie-scan (NetBox returns the existing tag on conflict; ignore non-zero)
nb POST /api/extras/tags/ '{"name":"ie-scan","slug":"ie-scan","color":"2196f3"}' >/dev/null || true

dev_json="$(nb GET "/api/dcim/devices/?name=${DEV}" || true)"
if ! printf '%s' "$dev_json" | python3 -c 'import json,sys; raise SystemExit(0 if json.load(sys.stdin).get("count") else 1)'; then
  created="$(nb POST /api/dcim/devices/ "{\"name\":\"${DEV}\",\"role\":{\"slug\":\"access-switch\"},\"device_type\":{\"slug\":\"e2e-model\"},\"site\":{\"slug\":\"${SITE}\"},\"status\":\"active\"}")"
  did="$(printf '%s' "$created" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
  iface="$(nb POST /api/dcim/interfaces/ "{\"device\":${did},\"name\":\"mgmt\",\"type\":\"virtual\"}")"
  iid="$(printf '%s' "$iface" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
  ipo="$(nb POST /api/ipam/ip-addresses/ "{\"address\":\"${IP}/32\",\"status\":\"active\",\"assigned_object_type\":\"dcim.interface\",\"assigned_object_id\":${iid}}")"
  ipid="$(printf '%s' "$ipo" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
  nb PATCH "/api/dcim/devices/${did}/" "{\"primary_ip4\":${ipid}}" >/dev/null
  echo "created device ${DEV} id ${did}"
else
  echo "device ${DEV} already exists"
fi

# prefix with the ie-scan tag
nb POST /api/ipam/prefixes/ "{\"prefix\":\"${PREFIX}\",\"status\":\"active\",\"site\":{\"slug\":\"${SITE}\"},\"tags\":[{\"slug\":\"ie-scan\"}]}" >/dev/null || echo "prefix create returned non-zero (it may already exist)"

echo "waiting for Prometheus http_sd (refresh_interval is 5m; override with IE_E2E_WAIT_SECONDS)"
WAIT="${IE_E2E_WAIT_SECONDS:-360}"
PROM="https://${PUBLIC_HOST}:${PORT_PROMETHEUS}"
found=0
end=$((SECONDS + WAIT))
while [ "$SECONDS" -lt "$end" ]; do
  if curl -fsS --cacert certs/ca.crt --resolve "${PUBLIC_HOST}:${PORT_PROMETHEUS}:127.0.0.1" \
      -u "$(envval ADMIN_BASIC_USER):$(envval ADMIN_BASIC_PASSWORD)" \
      "$PROM/api/v1/targets" | python3 -c 'import json,sys,os; d=json.load(sys.stdin); ip=os.environ["IP"];
hits=[t for t in d.get("data",{}).get("activeTargets",[]) if ip in (t.get("labels",{}).get("instance",""), t.get("labels",{}).get("ipv4",""), t.get("discoveredLabels",{}).get("__meta_netbox_primary_ip4",""), t.get("discoveredLabels",{}).get("__address__",""))];
raise SystemExit(0 if hits else 1)' IP="$IP"; then
    found=1
    break
  fi
  sleep 15
done
if [ "$found" -ne 1 ]; then
  echo "FAIL: Prometheus did not list ${IP} within ${WAIT}s" >&2
  exit 1
fi
echo "PASS: Prometheus has a target for ${IP}"

up="$(curl -fsS --cacert certs/ca.crt --resolve "${PUBLIC_HOST}:${PORT_PROMETHEUS}:127.0.0.1" \
  -u "$(envval ADMIN_BASIC_USER):$(envval ADMIN_BASIC_PASSWORD)" \
  --get "$PROM/api/v1/query" --data-urlencode "query=up{ipv4=\"${IP}\"}" || true)"
echo "up metric (informational; a documentation address will not answer): ${up:-none}"
if [ "${IE_E2E_REQUIRE_UP:-0}" = 1 ]; then
  printf '%s' "$up" | python3 -c 'import json,sys; d=json.load(sys.stdin); v=d["data"]["result"]; raise SystemExit(0 if v and v[0]["value"][1]=="1" else 1)'
fi

echo "Netdisco prefix file is written by ie-config into the netdisco-local volume."
echo "From the host, after ie-config has synced: docker compose exec netdisco-scheduler cat /home/netdisco/nd-site-local/scan-prefixes.txt"
echo "A device Netdisco finds that is not in NetBox shows up at GET /api/v1/discovery/unapproved (Administrator or Engineer session)."
echo "This script does not insert into Netdisco and does not claim an unapproved row appeared."
echo "done"
