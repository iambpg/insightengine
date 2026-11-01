#!/bin/sh
# Reads files written by ie-config and runs netdisco-do. No eval. No shell interpolation of the CIDR.
# The image ENTRYPOINT is replaced by `sh /scheduler.sh` so this file is what actually runs.
#
# A prefix is not passed to `discover -d <cidr>`. That command SNMP-walks every address.
# Netdisco's native range tool is `pingsweep` (ICMP, then discover only the replies) but it
# needs the ping binary and only notices hosts that answer ICMP. scripts/presweep.pl probes
# TCP, UDP/161 and ping in parallel and this script discovers only the live addresses.
# If the probe cannot run, and ping exists, fall back to `netdisco-do pingsweep`.
#
# One-shot lines (scan-once.txt) are handled before the prefix walk. A single address
# must not wait behind scan-now. Each line is "<id> <cidr>" or a bare CIDR. The id is
# the discovery_scans row; the result is written to scan-done/<id> and nothing else.
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

run_netdisco() {
  action=$1
  ip=$2
  rc=0
  netdisco-do "$action" -d "$ip" || rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "netdisco-do $action failed for $ip (exit $rc)" >&2
    return 1
  fi
  return 0
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
    rc=0
    perl "$PRESWEEP" "$cidr" > "$livef" || rc=$?
    if [ "$rc" -eq 3 ]; then
      echo "presweep: $cidr is larger than /16; not scanning it" >&2
      rm -f "$livef"
      return 1
    fi
    if [ "$rc" -eq 0 ]; then
      count=0
      if [ -s "$livef" ]; then
        count=$(grep -c . "$livef" || true)
      fi
      if [ "$count" -eq 0 ]; then
        echo "presweep dropped $cidr: no host answered TCP, UDP/161, or ping" >&2
        rm -f "$livef"
        return 2
      fi
      echo "presweep: $cidr answered $count host(s)" >&2
      fail=0
      while IFS= read -r ip || [ -n "$ip" ]; do
        printf '%s' "$ip" | grep -Eq '^[0-9]{1,3}(\.[0-9]{1,3}){3}$' || continue
        run_netdisco discover "$ip" || fail=1
        run_netdisco macsuck "$ip" || fail=1
        run_netdisco arpnip "$ip" || fail=1
      done < "$livef"
      rm -f "$livef"
      if [ "$fail" -ne 0 ]; then
        return 1
      fi
      return 0
    fi
    echo "presweep failed for $cidr (exit $rc); trying Netdisco pingsweep" >&2
    rm -f "$livef"
  fi
  if command -v ping >/dev/null 2>&1; then
    # Native Netdisco: ping the range, queue discover only for replies.
    rc=0
    netdisco-do pingsweep -d "$cidr" -e "${PRESWEEP_TIMEOUT:-0.4}" || rc=$?
    if [ "$rc" -ne 0 ]; then
      echo "netdisco-do pingsweep failed for $cidr (exit $rc)" >&2
      return 1
    fi
    return 0
  fi
  echo "presweep and ping are unavailable; not SNMP-scanning $cidr" >&2
  return 1
}

parse_target() {
  _id=""
  _cidr=""
  line=$(printf '%s' "$1" | tr -d '\r')
  case "$line" in
    ""|\#*) return 1 ;;
  esac
  first=${line%% *}
  rest=${line#* }
  if printf '%s' "$first" | grep -Eq '^[0-9]+$' && printf '%s' "$rest" | grep -Eq '^[0-9]{1,3}(\.[0-9]{1,3}){3}/[0-9]{1,2}$'; then
    _id=$first
    _cidr=$rest
    return 0
  fi
  if printf '%s' "$line" | grep -Eq '^[0-9]{1,3}(\.[0-9]{1,3}){3}/[0-9]{1,2}$'; then
    _cidr=$line
    return 0
  fi
  echo "ignoring scan target: $line" >&2
  return 1
}

write_scan_done() {
  id=$1
  rc=$2
  cidr=$3
  printf '%s' "$id" | grep -Eq '^[0-9]+$' || return 0
  mkdir -p "$DIR/scan-done"
  stamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  if [ "$rc" -eq 2 ]; then
    status=failed
    msg="presweep dropped $cidr: no host answered TCP, UDP/161, or ping"
  elif [ "$rc" -ne 0 ]; then
    status=failed
    msg="netdisco-do reported a failure for $cidr; see the scheduler log"
  else
    status=finished
    msg="Netdisco finished that probe. Devices that answered and are not in NetBox show up in this list."
  fi
  printf '%s\n%s\n%s\n' "$stamp" "$status" "$msg" > "$DIR/scan-done/$id"
}

walk_file() {
  file=$1
  [ -f "$file" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    parse_target "$line" || continue
    rc=0
    discover_live "$_cidr" || rc=$?
    write_scan_done "$_id" "$rc" "$_cidr"
  done < "$file"
}

run_pass() {
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
  # One-shot targets first, including a single address. They do not wait for scan-now.
  if [ -f "$DIR/scan-once.txt" ]; then
    mv "$DIR/scan-once.txt" "$DIR/scan-once.running"
    walk_file "$DIR/scan-once.running"
    rm -f "$DIR/scan-once.running"
  fi
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
  fi
}

last=0
if [ "${1:-}" = "--once" ]; then
  run_pass
  exit 0
fi
while true; do
  run_pass
  sleep 60
done
