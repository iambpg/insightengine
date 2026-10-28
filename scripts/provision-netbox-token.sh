#!/usr/bin/env bash
# Create a NetBox 4.6 v2 API token when the superuser already exists.
#
# netbox-docker's super_user.py creates the token only while it is creating the
# user, and only when SUPERUSER_API_KEY and SUPERUSER_API_TOKEN are both set.
# An install that already has the admin user (for example after copying an old
# Postgres volume) never receives that token. This script calls
# POST /api/users/tokens/provision/ and writes the returned nbt_<key>.<secret>
# into the secret files the installer has always used
# (secrets/prometheus/netbox.token, secrets/oxidized/netbox.token,
# secrets/cust-exporter/netbox.token). There is no secrets/netbox/ directory.
# An older file holds the raw 40-character token; lib-netbox-auth.sh sends that
# as Authorization: Token, and this script replaces it when NetBox rejects it.
# It does not print the token or the password.
#
#   ./scripts/provision-netbox-token.sh            # dry-run: report whether the current file works
#   ./scripts/provision-netbox-token.sh --apply
set -euo pipefail
umask 077
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
APPLY=0
SELF_TEST=0
case "${1:-}" in
  --apply) APPLY=1 ;;
  --self-test) SELF_TEST=1 ;;
  --help) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  "") ;;
  *) echo "unknown argument: $1" >&2; exit 2 ;;
esac

# NetBox 4.6.3 returns key (12 chars) and token (40-char secret, no nbt_ prefix).
# Older responses may already be nbt_<key>.<secret>. Empty if neither form is present.
compose_provision_token() {
  python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); t=d.get("token") or ""; k=d.get("key") or ""; print(t if t.startswith("nbt_") else ("nbt_%s.%s"%(k,t) if k and t else ""))' "$1"
}

if [ "$SELF_TEST" -eq 1 ]; then
  sample="$(mktemp)"
  trap 'rm -f "$sample"' EXIT
  printf '%s' '{"id":9,"key":"abcdefghijkl","token":"0123456789abcdef0123456789abcdef01234567"}' > "$sample"
  got="$(compose_provision_token "$sample")"
  [ "$got" = "nbt_abcdefghijkl.0123456789abcdef0123456789abcdef01234567" ]
  printf '%s' '{"id":9,"key":"abcdefghijkl","token":"nbt_abcdefghijkl.0123456789abcdef0123456789abcdef01234567"}' > "$sample"
  got="$(compose_provision_token "$sample")"
  [ "$got" = "nbt_abcdefghijkl.0123456789abcdef0123456789abcdef01234567" ]
  printf '%s' '{"id":9,"key":"","token":""}' > "$sample"
  got="$(compose_provision_token "$sample")"
  [ -z "$got" ]
  echo "PASS  provision token assembly"
  exit 0
fi

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
token="$(compose_provision_token "$resp")"
tid="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("id") or "")' "$resp")"
drop_provisioned() {
  # The 201 already created a token. Delete it when we cannot store it, so a
  # failed run does not leave an orphan that the next run would duplicate.
  [ -n "$token" ] && [ -n "$tid" ] || return 0
  printf 'Authorization: Bearer %s\n' "$token" > "$hdr"
  curl_api -o /dev/null -w '' -X DELETE -H @"$hdr" -H 'Accept: application/json' \
    "$base/api/users/tokens/${tid}/" || true
}
if ! printf '%s' "$token" | grep -Eq '^nbt_.+\..+'; then
  echo "provision response did not include a v2 token; deleting the token NetBox just created" >&2
  drop_provisioned
  unset token
  rm -f "$resp"
  exit 1
fi
write_one() {
  local path=$1 uid=$2
  mkdir -p "$(dirname "$path")"
  printf '%s' "$token" > "$path" || return 1
  chmod 400 "$path" || return 1
  if [ "$(id -u)" -eq 0 ]; then
    chown "$uid:$uid" "$path" || return 1
  fi
}
if ! write_one secrets/prometheus/netbox.token 65534 \
  || ! write_one secrets/oxidized/netbox.token 0 \
  || ! write_one secrets/cust-exporter/netbox.token 0; then
  echo "could not store the token; deleting it" >&2
  drop_provisioned
  unset token
  exit 1
fi
# Drop earlier insightengine tokens left by runs that exited before writing the files.
printf 'Authorization: Bearer %s\n' "$token" > "$hdr"
listf="${resp}.list"
if curl_api -o "$listf" -w '' -H @"$hdr" -H 'Accept: application/json' "$base/api/users/tokens/?limit=200"; then
  ids="$(python3 -c 'import json,sys
keep=sys.argv[1]
try:
    data=json.load(open(sys.argv[2]))
except (OSError, ValueError):
    data={}
for row in data.get("results") or []:
    if str(row.get("description") or "") != "insightengine":
        continue
    if str(row.get("id") or "") == keep:
        continue
    print(row.get("id") or "")
' "$tid" "$listf")"
  old=""
  for old in $ids; do
    [ -n "$old" ] || continue
    curl_api -o /dev/null -w '' -X DELETE -H @"$hdr" -H 'Accept: application/json' \
      "$base/api/users/tokens/${old}/" || true
  done
fi
rm -f "$resp" "$listf"
unset token
echo "wrote a new NetBox v2 token into the secret files (value not printed)"
echo "restart ie-config and prometheus, recreate oxidized and netbox-device-types so they read it:"
echo "  docker compose restart ie-config prometheus"
echo "  docker compose up -d --force-recreate --no-deps oxidized netbox-device-types"
