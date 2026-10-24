#!/usr/bin/env bash
# Store one secret file without echoing it or putting it on a command line.
# usage: scripts/set-secret.sh <relative path under secrets/>   (value read silently)
# example: scripts/set-secret.sh prometheus/netbox.token
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
rel="${1:?usage: $0 <path under secrets/>}"
case "$rel" in /*|*..*) echo "path must be relative, without .." >&2; exit 2 ;; esac
f="$ROOT/secrets/$rel"
[ -e "$f" ] || { echo "unknown secret file: secrets/$rel" >&2; exit 1; }
if [ -t 0 ]; then read -rsp "value for $rel: " v; echo >&2; else IFS= read -r v; fi
umask 077
printf '%s' "$v" > "$f"
echo "stored secrets/$rel (${#v} chars)"
echo "restart the services that use it: docker compose up -d --force-recreate <service>"
