#!/usr/bin/env bash
# Create a NetBox 4.6 v2 API token when the superuser already exists.
#
# netbox-docker's super_user.py creates the token only while it is creating the
# user, and only when SUPERUSER_API_KEY and SUPERUSER_API_TOKEN are both set.
# An install that already has the admin user (for example after copying an old
# Postgres volume) never receives that token. This script calls
# POST /api/users/tokens/provision/ and writes the returned nbt_<key>.<secret>
# into the secret files. It does not print the token or the password.
#
#   ./scripts/provision-netbox-token.sh            # dry-run: report whether the current file works
#   ./scripts/provision-netbox-token.sh --apply
set -euo pipefail
umask 077
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1
[ "${1:-}" = "--help" ] && { sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }
[ -f .env ] || { echo "no .env" >&2; exit 1; }

envval() {
  local line
  line="$(grep -E "^$1=" .env | tail -n1 || true)"
  line="${line#*=}"; line="${line#\'}"; line="${line%\'}"
  printf '%s' "$line"
}

# shellcheck disable=SC1091
. "$(dirname "$0")/lib-netbox-auth.sh"

hdr="$(mktemp)"
body="$(mktemp)"
resp="${body}.response"
trap 'rm -f "$hdr" "$body" "$resp"' EXIT
host="$(envval PUBLIC_HOST)"
port="$(envval PORT_NETBOX)"; port="${port:-8444}"
if [ -n "${NETBOX_INTERNAL_URL:-}" ]; then
  base="${NETBOX_INTERNAL_URL%/}"
  curl_api() { curl -sS "$@"; }
else
  base="https://${host}:${port}"
  curl_api() { curl -sS --cacert certs/ca.crt --resolve "${host}:${port}:127.0.0.1" "$@"; }
fi

if netbox_write_auth_header "$hdr"; then
  code="$(curl_api -o /dev/null -w '%{http_code}' -H @"$hdr" -H 'Accept: application/json' "$base/api/dcim/sites/?limit=1" || true)"
  if [ "$code" = "200" ]; then
    echo "existing NetBox token already works; secret files left unchanged"
    exit 0
  fi
  echo "existing token file did not authenticate (HTTP ${code:-none})"
fi

if [ "$APPLY" -ne 1 ]; then
  echo "dry-run: re-run with --apply after NetBox is up to provision a v2 token"
  exit 0
fi

user="$(envval NETBOX_SUPERUSER_NAME)"; user="${user:-admin}"
pass="$(envval NETBOX_SUPERUSER_PASSWORD)"
[ -n "$pass" ] || { echo "NETBOX_SUPERUSER_PASSWORD is empty" >&2; exit 1; }
printf '%s\n%s\n' "$user" "$pass" | python3 -c '
import json, sys
path = sys.argv[1]
user = sys.stdin.readline().rstrip("\n")
password = sys.stdin.readline().rstrip("\n")
with open(path, "w", encoding="utf-8") as fh:
    json.dump({"username": user, "password": password, "description": "insightengine"}, fh)
' "$body"
unset pass
code="$(curl_api -o "$resp" -w '%{http_code}' -H 'Content-Type: application/json' -H 'Accept: application/json' \
  -X POST "$base/api/users/tokens/provision/" -d @"$body" || true)"
rm -f "$body"
if [ "$code" != "201" ]; then
  echo "token provision failed (HTTP ${code})" >&2
  rm -f "$resp"
  exit 1
fi
token="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("token") or "")' "$resp")"
rm -f "$resp"
case "$token" in
  nbt_*.*) ;;
  *) echo "provision response did not include a v2 token" >&2; unset token; exit 1 ;;
esac
write_one() {
  local path=$1 uid=$2
  mkdir -p "$(dirname "$path")"
  printf '%s' "$token" > "$path"
  chmod 400 "$path" || true
  if [ "$(id -u)" -eq 0 ]; then
    chown "$uid:$uid" "$path" || true
  fi
}
write_one secrets/prometheus/netbox.token 65534
write_one secrets/oxidized/netbox.token 0
write_one secrets/cust-exporter/netbox.token 0
unset token
echo "wrote a new NetBox v2 token into the secret files (value not printed)"
echo "restart ie-config, prometheus and oxidized so they read it"
