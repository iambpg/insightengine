#!/usr/bin/env bash
# install.sh must leave each .env key once, including NETBOX_WORKER_REPLICAS.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
export INSTALL_SH_SOURCE_ONLY=1
export ENV_FILE="$tmp/.env"
# shellcheck disable=SC1091
source "$ROOT/install.sh"
cp "$ROOT/.env.example" "$ENV_FILE"
printf '\nNETBOX_WORKER_REPLICAS=9\n' >> "$ENV_FILE"
dedupe_env "$ENV_FILE"
count="$(grep -c '^NETBOX_WORKER_REPLICAS=' "$ENV_FILE")"
[ "$count" -eq 1 ]
setenv NETBOX_SUPERUSER_API_KEY abcdef123456
setenv NETBOX_WORKER_REPLICAS 3
count="$(grep -c '^NETBOX_WORKER_REPLICAS=' "$ENV_FILE")"
[ "$count" -eq 1 ]
grep -q "^NETBOX_WORKER_REPLICAS='3'$" "$ENV_FILE"
grep -q "^NETBOX_SUPERUSER_API_KEY='abcdef123456'$" "$ENV_FILE"
dupes="$(awk -F= '/^[A-Za-z_][A-Za-z0-9_]*=/ { print $1 }' "$ENV_FILE" | sort | uniq -d)"
[ -z "$dupes" ]
echo "PASS  .env keys are unique"
