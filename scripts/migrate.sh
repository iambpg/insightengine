#!/usr/bin/env bash
# =============================================================================
# migrate.sh - move data from the OLD stack into this stack. REVIEW-ONLY: never
# run against a live server before Phindani has reviewed it.
#
#   scripts/migrate.sh preflight   report what would be copied (read-only)
#   scripts/migrate.sh run         do the copy (needs a passing preflight)
#   scripts/migrate.sh status      print the progress file
#
# RULES
#  * The OLD stack is only READ (pg_dump, read-only bind mounts, config copies).
#    This script never stops, restarts, edits or deletes anything of the old
#    stack. Only containers of THIS stack are stopped/started.
#  * No secret is printed or logged. Database passwords come from a file
#    (OLD_*_PASSWORD_FILE) or a silent prompt, and are handed to the old
#    container over stdin (not on a command line).
#  * Prometheus history is NOT handled here (see scripts/prom-history.sh).
#  * Alertmanager/Caddy configs are copied for REVIEW into migration/imported/
#    and are NOT applied automatically.
#
# Settings: migration/migrate.conf (KEY=VALUE, mode 600; written by the setup service or copied from
# migration/migrate.conf.example). Progress: data/migration/progress.json
# (JSON lines). Log: data/migration/migrate-<timestamp>.log
# =============================================================================
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
CONF="${MIGRATE_CONF:-$ROOT/migration/migrate.conf}"
STATE_DIR="$ROOT/data/migration"
PROGRESS="$STATE_DIR/progress.json"
PREFLIGHT_JSON="$STATE_DIR/preflight.json"
mkdir -p "$STATE_DIR"
TS="$(date +%Y%m%d-%H%M%S)"
LOG="$STATE_DIR/migrate-$TS.log"

MODE="${1:-}"
ERRORS=0
WARNINGS=0

# ------------------------------------------------------------------ helpers
log()  { printf '%s %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$LOG" >&2; }
warn() { WARNINGS=$((WARNINGS + 1)); log "WARN  $*"; }
fail() { ERRORS=$((ERRORS + 1)); log "ERROR $*"; }
die()  { log "FATAL $*"; progress "fatal" "failed" "$*"; exit 1; }

json_escape() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g' | tr -d '\000-\037'; }
progress() {  # progress <step> <state> [detail]
  printf '{"time":"%s","step":"%s","state":"%s","detail":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(json_escape "$1")" "$(json_escape "$2")" "$(json_escape "${3:-}")" >> "$PROGRESS"
}

# Allow-listed KEY=VALUE parser (the file is never sourced/executed).
ALLOWED="OLD_COMPOSE_FILE OLD_STACK_DIR OLD_NETBOX_CONTAINER OLD_NETBOX_PG_CONTAINER OLD_NETBOX_DB OLD_NETBOX_DB_USER OLD_NETBOX_DB_PASSWORD_FILE OLD_NETDISCO_PG_CONTAINER OLD_NETDISCO_DB OLD_NETDISCO_DB_USER OLD_NETDISCO_DB_PASSWORD_FILE OLD_NETBOX_MEDIA_PATH OLD_GRAFANA_DATA_PATH OLD_GRAFANA_PROVISIONING_PATH OLD_GRAFANA_CONTAINER OLD_ALERTMANAGER_CONFIG_PATH OLD_CADDYFILE_PATH OLD_PROM_CONTAINER KEEP_DUMPS"
declare -A C=()
load_conf() {
  [ -f "$CONF" ] || die "settings file not found: $CONF"
  local line k v
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue ;; esac
    k="${line%%=*}"; v="${line#*=}"
    v="${v%\"}"; v="${v#\"}"; v="${v%\'}"; v="${v#\'}"
    case " $ALLOWED " in *" $k "*) C[$k]="$v" ;; *) warn "ignoring unknown setting $k" ;; esac
  done < "$CONF"
  C[KEEP_DUMPS]="${C[KEEP_DUMPS]:-yes}"
  C[OLD_NETBOX_DB]="${C[OLD_NETBOX_DB]:-netbox}"
  C[OLD_NETBOX_DB_USER]="${C[OLD_NETBOX_DB_USER]:-netbox}"
  C[OLD_NETDISCO_DB]="${C[OLD_NETDISCO_DB]:-netdisco}"
  C[OLD_NETDISCO_DB_USER]="${C[OLD_NETDISCO_DB_USER]:-netdisco}"
}

# new-stack env values (parsed, not sourced)
envval() { grep -E "^$1=" "$ROOT/.env" 2>/dev/null | head -n1 | cut -d= -f2- | sed "s/^'//; s/'\$//" || true; }

dc() { docker compose --project-directory "$ROOT" "$@"; }

ask_secret() {  # ask_secret <prompt> <file-or-empty>  -> prints secret to stdout
  if [ -n "${2:-}" ] && [ -r "$2" ]; then tr -d '\r\n' < "$2"; return; fi
  [ -t 0 ] || die "no password file set for $1 and no terminal for a prompt"
  local s; read -rsp "$1: " s; echo >&2; printf '%s' "$s"
}

human() { du -sh "$1" 2>/dev/null | cut -f1; }
need_dir() {  # need_dir <label> <path> (empty path = skipped)
  if [ -z "${2:-}" ]; then log "skip   $1 (not configured)"; return 1; fi
  if [ -d "$2" ] && [ -r "$2" ]; then log "ok     $1: $2 ($(human "$2"))"; return 0; fi
  fail "$1 not found/readable: $2"; return 1
}
need_file() {
  if [ -z "${2:-}" ]; then log "skip   $1 (not configured)"; return 1; fi
  if [ -f "$2" ] && [ -r "$2" ]; then log "ok     $1: $2"; return 0; fi
  fail "$1 not found/readable: $2"; return 1
}
container_running() { [ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null || echo false)" = "true" ]; }
container_image()   { docker inspect -f '{{.Config.Image}}' "$1" 2>/dev/null || echo "unknown"; }

# Run psql/pg_dump in the OLD container, password via stdin.
old_pg() {  # old_pg <container> <user> <passwordfile> <cmd...>
  local c=$1 u=$2 pf=$3 tool=$4; shift 4
  local pw; pw="$(ask_secret "password for old database user $u" "$pf")"
  printf '%s\n' "$pw" | docker exec -i "$c" sh -c 'IFS= read -r PGPASSWORD; export PGPASSWORD; exec "$@"' sh "$tool" -U "$u" "$@"
}
new_pg_exec() {  # new_pg_exec <service> <cmd...> ; stdin passes through
  dc exec -T "$1" "${@:2}"
}

# ----------------------------------------------------------------- preflight
preflight() {
  log "=== PREFLIGHT (read-only) ==="
  progress preflight running
  command -v docker >/dev/null || die "docker is not installed on this host"
  docker compose version >/dev/null 2>&1 || die "docker compose plugin missing"
  [ -f "$ROOT/.env" ] || die ".env not found - run install.sh first"

  # --- old containers
  local pairs=("netbox-postgres:${C[OLD_NETBOX_PG_CONTAINER]:-}" "netdisco-postgres:${C[OLD_NETDISCO_PG_CONTAINER]:-}" "netbox:${C[OLD_NETBOX_CONTAINER]:-}" "grafana:${C[OLD_GRAFANA_CONTAINER]:-}" "prometheus:${C[OLD_PROM_CONTAINER]:-}")
  local p name c
  for p in "${pairs[@]}"; do
    name="${p%%:*}"; c="${p#*:}"
    if [ -z "$c" ]; then log "skip   old $name container (not configured)"; continue; fi
    if container_running "$c"; then log "ok     old $name container '$c' running, image $(container_image "$c")"
    else fail "old $name container '$c' is not running (needed for read access)"; fi
  done

  # --- versions
  local oldpg newpg
  if [ -n "${C[OLD_NETBOX_PG_CONTAINER]:-}" ] && container_running "${C[OLD_NETBOX_PG_CONTAINER]}"; then
    oldpg="$(docker exec "${C[OLD_NETBOX_PG_CONTAINER]}" postgres --version 2>/dev/null || echo unknown)"
    log "info   old NetBox PostgreSQL: $oldpg"
  fi
  newpg="$(envval POSTGRES_IMAGE)"; log "info   new PostgreSQL image: ${newpg:-unset}"
  log "info   new NetBox image:     $(envval NETBOX_IMAGE)"
  if [ -n "${C[OLD_NETBOX_CONTAINER]:-}" ] && container_running "${C[OLD_NETBOX_CONTAINER]}"; then
    log "info   old NetBox release:   $(docker exec "${C[OLD_NETBOX_CONTAINER]}" sh -c 'cat /opt/netbox/netbox/release.yaml 2>/dev/null | grep -E "^version" | head -n1' 2>/dev/null || echo unknown)"
    warn "A restore only works UPWARDS: the new NetBox must be the same version or newer than the old one (it migrates the schema on first start). Compare the two lines above."
  fi
  log "info   a pg_dump restore into a newer PostgreSQL major is supported; into an OLDER one is not."

  # --- sizes
  if [ -n "${C[OLD_NETBOX_PG_CONTAINER]:-}" ] && container_running "${C[OLD_NETBOX_PG_CONTAINER]}"; then
    local sz
    sz="$(old_pg "${C[OLD_NETBOX_PG_CONTAINER]}" "${C[OLD_NETBOX_DB_USER]}" "${C[OLD_NETBOX_DB_PASSWORD_FILE]:-}" psql -d "${C[OLD_NETBOX_DB]}" -Atc "select pg_size_pretty(pg_database_size(current_database()))" 2>/dev/null || true)"
    if [ -n "$sz" ]; then log "info   old NetBox database size: $sz"; else warn "cannot query the old NetBox database (credentials?)"; fi
  fi
  if [ -n "${C[OLD_NETDISCO_PG_CONTAINER]:-}" ] && container_running "${C[OLD_NETDISCO_PG_CONTAINER]}"; then
    local sz2
    sz2="$(old_pg "${C[OLD_NETDISCO_PG_CONTAINER]}" "${C[OLD_NETDISCO_DB_USER]}" "${C[OLD_NETDISCO_DB_PASSWORD_FILE]:-}" psql -d "${C[OLD_NETDISCO_DB]}" -Atc "select pg_size_pretty(pg_database_size(current_database()))" 2>/dev/null || true)"
    if [ -n "$sz2" ]; then log "info   old Netdisco database size: $sz2"; else warn "cannot query the old Netdisco database (credentials?)"; fi
  fi
  need_dir "NetBox media"            "${C[OLD_NETBOX_MEDIA_PATH]:-}" || true
  need_dir "Grafana data"            "${C[OLD_GRAFANA_DATA_PATH]:-}" || true
  need_dir "Grafana provisioning"    "${C[OLD_GRAFANA_PROVISIONING_PATH]:-}" || true
  need_file "Alertmanager config"    "${C[OLD_ALERTMANAGER_CONFIG_PATH]:-}" || true
  need_file "Caddyfile"              "${C[OLD_CADDYFILE_PATH]:-}" || true
  if [ -n "${C[OLD_GRAFANA_DATA_PATH]:-}" ] && [ -d "${C[OLD_GRAFANA_DATA_PATH]}" ] && [ ! -f "${C[OLD_GRAFANA_DATA_PATH]}/grafana.db" ]; then
    fail "no grafana.db in ${C[OLD_GRAFANA_DATA_PATH]}"
  fi

  # --- disk space for dumps (estimate: 1x database size on ROOT filesystem)
  log "info   free space for dumps/copies in $STATE_DIR: $(df -h "$STATE_DIR" | awk 'NR==2{print $4}')"

  # --- port conflicts (old stack keeps running!)
  local ports="18086 443 3000 9090 8086 8081 5000 8888 8092 9116 9115 57500 514 162" busy=""
  for port in $ports; do
    if ss -Hltun 2>/dev/null | awk '{print $5}' | grep -qE "[:.]$port\$"; then busy="$busy $port"; fi
  done
  if [ -n "$busy" ]; then warn "ports in use on this host:$busy. The old stack stays running, so give this stack other host ports in .env (PORT_HTTP, PORT_HTTPS, PORT_GRAFANA, ...) until you cut over."; fi

  # --- new stack state
  if [ -n "$(dc ps -q 2>/dev/null || true)" ]; then log "info   new stack containers exist: running 'run' will stop only the new NetBox/Netdisco/Grafana containers during restore"; fi

  log "result: $ERRORS error(s), $WARNINGS warning(s)"
  printf '{"time":"%s","errors":%d,"warnings":%d,"log":"%s"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$ERRORS" "$WARNINGS" "$(json_escape "$LOG")" > "$PREFLIGHT_JSON"
  progress preflight "$([ "$ERRORS" -eq 0 ] && echo passed || echo failed)" "$ERRORS error(s), $WARNINGS warning(s)"
  return "$ERRORS"
}

# ----------------------------------------------------------------------- run
copy_db() {  # copy_db <label> <old container> <old db> <old user> <old pwfile> <new service> <new db> <new user>
  local label=$1 oc=$2 odb=$3 ou=$4 opf=$5 nsvc=$6 ndb=$7 nu=$8
  [ -n "$oc" ] || { log "skip   $label (no old container configured)"; return 0; }
  progress "$label-db" running
  log "step   $label database: dump (old, read-only) -> restore (new)"
  local dump="" tee_target=/dev/null
  if [ "${C[KEEP_DUMPS]}" = "yes" ]; then
    mkdir -p "$STATE_DIR/dumps"; dump="$STATE_DIR/dumps/$label-$TS.dump"; tee_target="$dump"
  fi
  old_pg "$oc" "$ou" "$opf" pg_dump -Fc --no-owner --no-acl -d "$odb" | tee "$tee_target" | new_pg_exec "$nsvc" pg_restore -U "$nu" -d "$ndb" --no-owner --no-acl --clean --if-exists --exit-on-error \
    || { progress "$label-db" failed; die "$label database copy failed (the old database was not modified; see $LOG)"; }
  [ -z "$dump" ] || log "info   dump kept at $dump (contains data - protect it; delete when no longer needed)"
  progress "$label-db" "done"
}

copy_dir_into_service() {  # copy_dir_into_service <label> <src> <service> <dest in container> <chown uid:gid>
  local label=$1 src=$2 svc=$3 dest=$4 own=$5
  [ -n "$src" ] || { log "skip   $label (not configured)"; return 0; }
  progress "$label" running
  log "step   $label: $src -> $svc:$dest"
  dc run --rm --no-deps --user root --entrypoint sh -v "$src:/migrate-src:ro" "$svc" -c "mkdir -p '$dest' && cp -a /migrate-src/. '$dest'/ && chown -R $own '$dest'" >> "$LOG" 2>&1 \
    || { progress "$label" failed; die "$label copy failed (see $LOG)"; }
  progress "$label" "done"
}

run() {
  log "=== MIGRATE RUN $TS ==="
  : > "$PROGRESS"
  preflight || die "preflight has errors - fix them first (nothing was changed)"
  local nb_db nb_user nd_db nd_user
  nb_db="$(envval NETBOX_DB_NAME)"; nb_db="${nb_db:-netbox}"; nb_user="$(envval NETBOX_DB_USER)"; nb_user="${nb_user:-netbox}"
  nd_db="$(envval NETDISCO_DB_NAME)"; nd_db="${nd_db:-netdisco}"; nd_user="$(envval NETDISCO_DB_USER)"; nd_user="${nd_user:-netdisco}"

  progress prepare running
  log "step   start the NEW databases and stop the NEW app containers that use them"
  dc up -d netbox-postgres netdisco-postgres >> "$LOG" 2>&1
  dc stop netbox netbox-worker netdisco-web netdisco-backend grafana >> "$LOG" 2>&1 || true
  for _ in $(seq 1 60); do
    [ "$(docker inspect -f '{{.State.Health.Status}}' "$(dc ps -q netbox-postgres)" 2>/dev/null)" = "healthy" ] && break
    sleep 2
  done
  progress prepare "done"

  copy_db netbox   "${C[OLD_NETBOX_PG_CONTAINER]:-}"   "${C[OLD_NETBOX_DB]}"   "${C[OLD_NETBOX_DB_USER]}"   "${C[OLD_NETBOX_DB_PASSWORD_FILE]:-}"   netbox-postgres   "$nb_db" "$nb_user"
  copy_db netdisco "${C[OLD_NETDISCO_PG_CONTAINER]:-}" "${C[OLD_NETDISCO_DB]}" "${C[OLD_NETDISCO_DB_USER]}" "${C[OLD_NETDISCO_DB_PASSWORD_FILE]:-}" netdisco-postgres "$nd_db" "$nd_user"

  # TODO(Phindani): 'unit' is the NetBox container user in netbox-docker images; confirm for the pinned image.
  copy_dir_into_service netbox-media "${C[OLD_NETBOX_MEDIA_PATH]:-}" netbox /opt/netbox/netbox/media "\$(id -u unit 2>/dev/null || echo 999):0"
  if [ -n "${C[OLD_GRAFANA_DATA_PATH]:-}" ]; then
    # grafana.db holds users, dashboards, folders, datasources and alert rules
    progress grafana running
    log "step   grafana: copy grafana.db (dashboards, users, datasources)"
    dc run --rm --no-deps --user root --entrypoint sh -v "${C[OLD_GRAFANA_DATA_PATH]}:/migrate-src:ro" grafana -c "cp -a /migrate-src/grafana.db /var/lib/grafana/grafana.db && chown 472:0 /var/lib/grafana/grafana.db" >> "$LOG" 2>&1 \
      || { progress grafana failed; die "grafana copy failed (see $LOG)"; }
    progress grafana "done"
  fi

  progress config-review running
  local imp="$ROOT/migration/imported/$TS"; mkdir -p "$imp"; chmod 700 "$imp" "$ROOT/migration/imported"
  [ -z "${C[OLD_ALERTMANAGER_CONFIG_PATH]:-}" ] || cp -p "${C[OLD_ALERTMANAGER_CONFIG_PATH]}" "$imp/alertmanager.yml"
  [ -z "${C[OLD_CADDYFILE_PATH]:-}" ]           || cp -p "${C[OLD_CADDYFILE_PATH]}" "$imp/Caddyfile"
  [ -z "${C[OLD_GRAFANA_PROVISIONING_PATH]:-}" ] || cp -a "${C[OLD_GRAFANA_PROVISIONING_PATH]}" "$imp/grafana-provisioning"
  log "info   old configs copied for REVIEW to $imp (may contain webhook URLs/secrets; NOT applied)"
  progress config-review "done"

  progress complete "done" "see $LOG"
  cat >&2 <<NEXT

Migration finished. The OLD stack was not touched.
Next (manual, in this order):
  1. Review $imp and port what you still need by hand
     (webhook URLs -> config/alert-relay/destinations.json, routes -> config/alertmanager/).
  2. Create NEW read-only NetBox API tokens for Prometheus and Oxidized and store them
     with scripts/set-secret.sh (the old tokens' values are not reusable here).
  3. Start this stack:  docker compose up -d   (use other host ports until cutover).
  4. Compare both stacks, then cut over yourself (stop the old stack MANUALLY).
  5. Prometheus history: optional, separate -> scripts/prom-history.sh
ROLLBACK: see README section "Rollback". In short, stop this stack (docker compose down,
WITHOUT -v) and keep using the old one; nothing there was changed.
NEXT
}

case "$MODE" in
  preflight) load_conf; : > "$PROGRESS"; preflight ;;
  run)       load_conf; run ;;
  status)    [ -f "$PROGRESS" ] && cat "$PROGRESS" || echo "no migration has run" ;;
  *) echo "usage: $0 preflight|run|status" >&2; exit 2 ;;
esac
