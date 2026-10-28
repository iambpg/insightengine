#!/bin/sh
# Reads files written by ie-config and runs netdisco-do. No eval. No shell interpolation of the CIDR.
# The image ENTRYPOINT is replaced by `sh /scheduler.sh` so this file is what actually runs.
#
# A prefix is not passed to `discover -d <cidr>`. That command SNMP-walks every address.
# Netdisco's native range tool is `pingsweep` (ICMP, then discover only the replies) but it
# needs the ping binary and only notices hosts that answer ICMP. scripts/presweep.pl probes
# TCP, UDP/161 and ping in parallel and this script discovers only the live addresses.
# If the probe cannot run, and ping exists, fall back to `netdisco-do pingsweep`.
set -eu
DIR="${NETDISCO_LOCAL_DIR:-/home/netdisco/nd-site-local}"
PRESWEEP="${PRESWEEP_BIN:-/presweep.pl}"
mkdir -p "$DIR"

read_presweep_env() {
  file="$DIR/presweep.env"
  [ -f "$file" ] || return 0
  raw=$(grep -E '^PRESWEEP_TIMEOUT=' "$file" 2>/dev/null | head -n1 | cut -d= -f2- | tr -cd '0-9.' || true)
  if printf '%s' "$raw" | grep -Eq '^[0-9]+(\.[0-9]+)?$'; then
    PRESWEEP_TIMEOUT=$raw
  fi
  raw=$(grep -E '^PRESWEEP_PARALLEL=' "$file" 2>/dev/null | head -n1 | cut -d= -f2- | tr -cd '0-9' || true)
  if printf '%s' "$raw" | grep -Eq '^[0-9]+$'; then
    PRESWEEP_PARALLEL=$raw
  fi
}

discover_live() {
  cidr=$1
  printf '%s' "$cidr" | grep -Eq '^[0-9]{1,3}(\.[0-9]{1,3}){3}/[0-9]{1,2}$' || return 0
  read_presweep_env
  export PRESWEEP_TIMEOUT="${PRESWEEP_TIMEOUT:-0.4}"
  export PRESWEEP_PARALLEL="${PRESWEEP_PARALLEL:-64}"
  livef="$DIR/presweep-live.$$"
  rm -f "$livef"
  if [ -f "$PRESWEEP" ] && command -v perl >/dev/null 2>&1; then
    set +e
    perl "$PRESWEEP" "$cidr" > "$livef"
    rc=$?
    set -e
    if [ "$rc" -eq 3 ]; then
      echo "presweep: $cidr is larger than /16; not scanning it" >&2
      rm -f "$livef"
      return 0
    fi
    if [ "$rc" -eq 0 ]; then
      if [ -s "$livef" ]; then
        while IFS= read -r ip || [ -n "$ip" ]; do
          printf '%s' "$ip" | grep -Eq '^[0-9]{1,3}(\.[0-9]{1,3}){3}$' || continue
          netdisco-do discover -d "$ip" || true
          netdisco-do macsuck -d "$ip" || true
          netdisco-do arpnip -d "$ip" || true
        done < "$livef"
      fi
      rm -f "$livef"
      return 0
    fi
    echo "presweep failed for $cidr (exit $rc); trying Netdisco pingsweep" >&2
    rm -f "$livef"
  fi
  if command -v ping >/dev/null 2>&1; then
    # Native Netdisco: ping the range, queue discover only for replies.
    netdisco-do pingsweep -d "$cidr" -e "${PRESWEEP_TIMEOUT:-0.4}" || true
  else
    echo "presweep and ping are unavailable; not SNMP-scanning $cidr" >&2
  fi
}

walk_file() {
  file=$1
  [ -f "$file" ] || return 0
  while IFS= read -r cidr || [ -n "$cidr" ]; do
    discover_live "$cidr"
  done < "$file"
}

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
    walk_file "$DIR/scan-prefixes.txt"
    last=$now
    date -u +%Y-%m-%dT%H:%M:%SZ > "$DIR/scan-finished" 2>/dev/null || true
  fi
  # One-shot targets from POST /api/v1/discovery/scan. Removed before the walk so a retry does not duplicate them.
  if [ -f "$DIR/scan-once.txt" ]; then
    mv "$DIR/scan-once.txt" "$DIR/scan-once.running"
    walk_file "$DIR/scan-once.running"
    rm -f "$DIR/scan-once.running"
    date -u +%Y-%m-%dT%H:%M:%SZ > "$DIR/scan-finished" 2>/dev/null || true
  fi
  sleep 60
done
