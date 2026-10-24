#!/usr/bin/env bash
# =============================================================================
# prom-history.sh - OPTIONAL, SEPARATE step: import the OLD Prometheus history.
# The installer does not decide this. The Settings page triggers it later as
# "keep history" (this script) or "start fresh" (do nothing).
#
#   scripts/prom-history.sh check                       read-only: sizes/blocks
#   scripts/prom-history.sh import --from-snapshot URL DATA_DIR
#         URL      old Prometheus base URL (needs --web.enable-admin-api; the
#                  snapshot call is a POST that creates hard links inside the
#                  OLD data dir under snapshots/ - it changes nothing else)
#         DATA_DIR host path of the OLD Prometheus data directory
#   scripts/prom-history.sh import --from-dir DATA_DIR
#         copies only COMPLETE blocks (ULID directories) from the old data dir;
#         the unflushed head (about the last 2h, WAL) is not copied.
#
# Never stops or modifies the old Prometheus (besides the snapshot hard links,
# which are left in place for you to remove later). Only the NEW prometheus is
# stopped while blocks are copied into its volume. Plan for a short gap in the
# new graphs during that restart.
# =============================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
STATE_DIR="$ROOT/data/migration"; mkdir -p "$STATE_DIR"
LOG="$STATE_DIR/prom-history-$(date +%Y%m%d-%H%M%S).log"
log() { printf '%s %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$LOG" >&2; }
dc() { docker compose --project-directory "$ROOT" "$@"; }
is_block() { case "$1" in [0-9A-HJKMNP-TV-Z][0-9A-HJKMNP-TV-Z]*) [ "${#1}" -eq 26 ] ;; *) return 1 ;; esac; }

list_blocks() {  # list_blocks <dir>
  local d
  for d in "$1"/*/; do
    d="${d%/}"
    if is_block "$(basename "$d")" && [ -f "$d/meta.json" ]; then echo "$d"; fi
  done
  return 0
}

cmd="${1:-}"; shift || true
case "$cmd" in
  check)
    dir="${1:?usage: check DATA_DIR}"
    [ -d "$dir" ] || { log "no such directory $dir"; exit 1; }
    n=$(list_blocks "$dir" | wc -l)
    log "old TSDB: $n complete blocks, total $(du -sh "$dir" | cut -f1)"
    log "new retention: $(grep -E '^PROM_RETENTION_TIME=' .env 2>/dev/null | cut -d= -f2- || echo default 30d) - blocks older than that are removed after import"
    ;;
  import)
    mode="${1:-}"; src=""
    case "$mode" in
      --from-snapshot)
        url="${2:?need old Prometheus URL}"; olddir="${3:?need old data dir}"
        log "requesting snapshot from the old Prometheus (admin API)"
        resp="$(curl -fsS -m 300 -X POST "$url/api/v1/admin/tsdb/snapshot")" || { log "snapshot call failed (admin API not enabled? use --from-dir)"; exit 1; }
        name="$(printf '%s' "$resp" | sed -n 's/.*"name":"\([^"]*\)".*/\1/p')"
        [ -n "$name" ] && [ -d "$olddir/snapshots/$name" ] || { log "snapshot not found under $olddir/snapshots"; exit 1; }
        src="$olddir/snapshots/$name"
        log "snapshot $name ready (left in the old data dir; remove it yourself later)"
        ;;
      --from-dir) src="${2:?need old data dir}"; [ -d "$src" ] || { log "no such directory $src"; exit 1; } ;;
      *) echo "usage: $0 import --from-snapshot URL DATA_DIR | --from-dir DATA_DIR" >&2; exit 2 ;;
    esac
    blocks="$(list_blocks "$src" | xargs -r -n1 basename | tr '\n' ' ')"
    [ -n "$blocks" ] || { log "no complete blocks found in $src"; exit 1; }
    log "will copy blocks: $blocks"
    log "stopping the NEW prometheus only"
    dc stop prometheus >> "$LOG" 2>&1 || true
    # shellcheck disable=SC2016
    dc run --rm --no-deps --user root --entrypoint sh -v "$src:/import-src:ro" prometheus -c '
      for b in '"$blocks"'; do
        [ -e "/prometheus/$b" ] && continue
        cp -a "/import-src/$b" "/prometheus/$b"
      done
      chown -R 65534:65534 /prometheus' >> "$LOG" 2>&1 || { log "copy failed (see $LOG); new prometheus left stopped"; exit 1; }
    log "starting the NEW prometheus"
    dc up -d prometheus >> "$LOG" 2>&1
    log "done. Check the graphs; overlapping time ranges are merged by Prometheus."
    ;;
  *) echo "usage: $0 check DATA_DIR | import --from-snapshot URL DATA_DIR | import --from-dir DATA_DIR" >&2; exit 2 ;;
esac
