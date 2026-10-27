#!/usr/bin/env bash
# Creates the client's root objects in NetBox (idempotent): a Tenant and a root
# Region named after CLIENT_NAME / CLIENT_SLUG from .env. Run after NetBox is up.
#
# Token: reads the NetBox API token from the file given in NETBOX_TOKEN_FILE,
# else from secrets/prometheus/netbox.token unless it is still the placeholder,
# else from NETBOX_SUPERUSER_API_TOKEN in .env. The token is passed to curl via
# a private header file (never on the command line, never printed).
#
# TODO(Phindani): NetBox 4.5+ uses v2 tokens ("nbt_<key>.<token>", sent as
# "Authorization: Bearer ..."); older versions use "Token <token>". The script
# picks the scheme from the prefix. Confirm against the NetBox version you pin.
set -euo pipefail
umask 077
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[ -f .env ] || { echo "no .env - run ./install.sh first" >&2; exit 1; }

envval() { local l; l="$(grep -E "^$1=" .env | head -n1 || true)"; l="${l#*=}"; l="${l#\'}"; l="${l%\'}"; printf '%s' "$l"; }
CLIENT_NAME="$(envval CLIENT_NAME)"; CLIENT_SLUG="$(envval CLIENT_SLUG)"
PUBLIC_HOST="$(envval PUBLIC_HOST)"; PORT_NETBOX="$(envval PORT_NETBOX)"; PORT_NETBOX="${PORT_NETBOX:-8444}"
if [ -z "$CLIENT_SLUG" ] || [ "$CLIENT_SLUG" = unconfigured ]; then
  echo "client not set yet - finish the first-run page (/setup/) first" >&2
  exit 1
fi

tok=""
if [ -n "${NETBOX_TOKEN_FILE:-}" ]; then tok="$(cat "$NETBOX_TOKEN_FILE")"
elif [ -s secrets/prometheus/netbox.token ] && [ "$(cat secrets/prometheus/netbox.token)" != "unset-placeholder" ]; then tok="$(cat secrets/prometheus/netbox.token)"
else tok="$(envval NETBOX_SUPERUSER_API_TOKEN)"; fi
[ -n "$tok" ] || { echo "no API token available" >&2; exit 1; }

hdr="$(mktemp)"; trap 'rm -f "$hdr"' EXIT
case "$tok" in nbt_*) printf 'Authorization: Bearer %s\n' "$tok" > "$hdr" ;; *) printf 'Authorization: Token %s\n' "$tok" > "$hdr" ;; esac
unset tok
# Inside the setup container, NETBOX_INTERNAL_URL=http://netbox:8080 (the public --resolve target is the container itself).
if [ -n "${NETBOX_INTERNAL_URL:-}" ]; then
  BASE="${NETBOX_INTERNAL_URL%/}"
  api() {  # api METHOD PATH [json]
    local m=$1 p=$2 d=${3:-}
    if [ -n "$d" ]; then
      curl -fsS -H @"$hdr" -H 'Content-Type: application/json' -H 'Accept: application/json' -X "$m" "$BASE$p" -d "$d"
    else
      curl -fsS -H @"$hdr" -H 'Accept: application/json' -X "$m" "$BASE$p"
    fi
  }
else
  BASE="https://${PUBLIC_HOST}:${PORT_NETBOX}"
  api() {  # api METHOD PATH [json]
    local m=$1 p=$2 d=${3:-}
    if [ -n "$d" ]; then
      curl -fsS --cacert certs/ca.crt --resolve "${PUBLIC_HOST}:${PORT_NETBOX}:127.0.0.1" -H @"$hdr" -H 'Content-Type: application/json' -H 'Accept: application/json' -X "$m" "$BASE$p" -d "$d"
    else
      curl -fsS --cacert certs/ca.crt --resolve "${PUBLIC_HOST}:${PORT_NETBOX}:127.0.0.1" -H @"$hdr" -H 'Accept: application/json' -X "$m" "$BASE$p"
    fi
  }
fi
json_str() { python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$1"; }
ensure() {  # ensure <label> <list-path> <slug> <json body>
  local label=$1 path=$2 slug=$3 body=$4 cnt
  cnt="$(api GET "$path?slug=$slug" | python3 -c 'import json,sys;print(json.load(sys.stdin)["count"])')"
  if [ "$cnt" = 0 ]; then api POST "$path" "$body" >/dev/null; echo "created $label '$slug'"; else echo "$label '$slug' already exists"; fi
}
N="$(json_str "$CLIENT_NAME")"; S="$(json_str "$CLIENT_SLUG")"
ensure tenant /api/tenancy/tenants/ "$CLIENT_SLUG" "{\"name\": $N, \"slug\": $S}"
ensure region /api/dcim/regions/    "$CLIENT_SLUG" "{\"name\": $N, \"slug\": $S}"
ensure tag /api/extras/tags/ ie-scan '{"name":"ie-scan","slug":"ie-scan","color":"2196f3"}'
# Device roles the Prometheus jobs select. A device with one of these roles and a primary IP is monitored.
for pair in \
  access-switch:"Access switch" \
  core-switch:"Core switch" \
  distribution-switch:"Distribution switch" \
  sdwan:"SD-WAN" \
  hub:"Hub firewall" \
  core-firewall:"Core firewall" \
  wireless-controller:"Wireless controller"
do
  slug="${pair%%:*}"
  label="${pair#*:}"
  ensure "device role" /api/dcim/device-roles/ "$slug" "{\"name\":$(json_str "$label"),\"slug\":$(json_str "$slug"),\"color\":\"2196f3\"}"
done
echo "done. Add a device with status active and a primary IP, or a prefix tagged ie-scan."
