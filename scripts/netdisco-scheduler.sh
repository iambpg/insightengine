#!/bin/sh
# Reads files written by ie-config and runs netdisco-do. No eval. No shell interpolation of the CIDR.
# The image ENTRYPOINT is replaced by `sh /scheduler.sh` so this file is what actually runs.
set -eu
DIR="${NETDISCO_LOCAL_DIR:-/home/netdisco/nd-site-local}"
mkdir -p "$DIR"
last=0
while true; do
  now=$(date +%s)
  interval=6
  if [ -f "$DIR/interval-hours" ]; then
    raw=$(tr -cd '0-9' < "$DIR/interval-hours" | cut -c1-4)
    if [ -n "$raw" ]; then
      interval=$raw
    fi
  fi
  # interval is digits only; arithmetic is safe
  if [ "$interval" -lt 1 ]; then interval=1; fi
  if [ "$interval" -gt 168 ]; then interval=168; fi
  window=$((interval * 3600))
  scan=0
  if [ -f "$DIR/scan-now" ]; then
    rm -f "$DIR/scan-now"
    scan=1
  fi
  if [ $((now - last)) -ge "$window" ]; then
    scan=1
  fi
  if [ "$scan" -eq 1 ] && [ -f "$DIR/scan-prefixes.txt" ]; then
    while IFS= read -r cidr || [ -n "$cidr" ]; do
      printf '%s' "$cidr" | grep -Eq '^[0-9]{1,3}(\.[0-9]{1,3}){3}/[0-9]{1,2}$' || continue
      netdisco-do discover -d "$cidr" || true
      netdisco-do macsuck -d "$cidr" || true
      netdisco-do arpnip -d "$cidr" || true
    done < "$DIR/scan-prefixes.txt"
    last=$now
  fi
  sleep 60
done
