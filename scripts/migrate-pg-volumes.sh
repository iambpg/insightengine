#!/usr/bin/env bash
# Copy Postgres data out of anonymous volumes left by the old compose mount.
#
# postgres:17.9 keeps the cluster in /var/lib/postgresql/data (the image VOLUME).
# Older compose files mounted the named volume at /var/lib/postgresql, so Docker
# stored the real cluster in an anonymous volume. `docker compose down` orphans
# that volume and the next `up` starts empty.
#
# The fixed compose file mounts the named volume at /var/lib/postgresql/data and
# sets PGDATA=/var/lib/postgresql/data/pgdata. Run this AFTER `docker compose down`
# and BEFORE `docker compose up` on an install that already has data.
#
#   ./scripts/migrate-pg-volumes.sh              # dry-run (default)
#   ./scripts/migrate-pg-volumes.sh --apply      # copy into <named-volume>/pgdata
#   ./scripts/migrate-pg-volumes.sh --apply --remove-source
#
# Idempotent: if pgdata/PG_VERSION already exists, the copy is skipped unless
# --force is given. The source volume is never deleted unless --remove-source.
# The script does not print passwords.
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

APPLY=0
FORCE=0
REMOVE_SOURCE=0
PROJECT="${COMPOSE_PROJECT_NAME:-}"
POSTGRES_IMAGE="${POSTGRES_IMAGE:-postgres:17.9}"

usage() {
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --apply) APPLY=1; shift ;;
    --dry-run) APPLY=0; shift ;;
    --force) FORCE=1; shift ;;
    --remove-source) REMOVE_SOURCE=1; shift ;;
    --project) PROJECT="${2:-}"; shift 2 ;;
    --image) POSTGRES_IMAGE="${2:-}"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is not available; nothing was changed" >&2
  exit 1
fi

if [ -z "$PROJECT" ]; then
  PROJECT="$(basename "$ROOT" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9')"
  [ -n "$PROJECT" ] || PROJECT="insightengine"
fi

say() { printf '%s\n' "$*"; }

volume_exists() {
  docker volume inspect "$1" >/dev/null 2>&1
}

# Named compose volume: <project>_<volume>. Also accept an explicit name.
named_volume() {
  local volume_key=$1
  local candidate="${PROJECT}_${volume_key}"
  if volume_exists "$candidate"; then
    printf '%s' "$candidate"
    return 0
  fi
  # Compose may prefix with the directory name rather than COMPOSE_PROJECT_NAME history.
  local found
  found="$(docker volume ls --format '{{.Name}}' | grep -E "(^|_)${volume_key}$" | head -n1 || true)"
  printf '%s' "$found"
}

# Anonymous volumes are 64-hex names. Prefer ones labeled for the service.
# Prints candidate names, one per line, best first.
anonymous_candidates() {
  local service=$1
  docker volume ls -q | while IFS= read -r name; do
    [ -n "$name" ] || continue
    printf '%s' "$name" | grep -Eq '^[0-9a-f]{64}$' || continue
    labels="$(docker volume inspect -f '{{json .Labels}}' "$name" 2>/dev/null || true)"
    case "$labels" in
      *"\"com.docker.compose.service\":\"${service}\""*) printf '1 %s\n' "$name" ;;
      *) printf '2 %s\n' "$name" ;;
    esac
  done | sort | cut -d' ' -f2-
}

volume_has_pg() {
  local volume=$1 sub=${2:-}
  local target="/v"
  [ -n "$sub" ] && target="/v/${sub}"
  docker run --rm -v "${volume}:/v:ro" --entrypoint /bin/sh "$POSTGRES_IMAGE" \
    -c "test -f ${target}/PG_VERSION" >/dev/null 2>&1
}

volume_pg_version() {
  local volume=$1 sub=${2:-}
  local target="/v/PG_VERSION"
  [ -n "$sub" ] && target="/v/${sub}/PG_VERSION"
  docker run --rm -v "${volume}:/v:ro" --entrypoint /bin/sh "$POSTGRES_IMAGE" \
    -c "cat ${target} 2>/dev/null || true"
}

# Copy the cluster at the root of $src into $dest/pgdata. Skip when the
# destination already has PG_VERSION unless --force.
copy_cluster() {
  local src=$1 dest=$2
  if volume_has_pg "$dest" pgdata && [ "$FORCE" -ne 1 ]; then
    say "  skip: ${dest}/pgdata already has PG_VERSION (use --force to overwrite)"
    return 0
  fi
  if [ "$APPLY" -ne 1 ]; then
    say "  dry-run: would copy ${src} -> ${dest}/pgdata"
    return 0
  fi
  say "  copying ${src} -> ${dest}/pgdata"
  docker run --rm \
    -v "${src}:/from:ro" \
    -v "${dest}:/to" \
    --entrypoint /bin/sh "$POSTGRES_IMAGE" \
    -c 'set -eu
      if [ ! -f /from/PG_VERSION ]; then echo "source has no PG_VERSION" >&2; exit 1; fi
      mkdir -p /to/pgdata
      if [ -f /to/pgdata/PG_VERSION ]; then rm -rf /to/pgdata; mkdir -p /to/pgdata; fi
      cp -a /from/. /to/pgdata/
      chown -R postgres:postgres /to/pgdata
      test -f /to/pgdata/PG_VERSION
    '
  say "  copied (PG_VERSION $(volume_pg_version "$dest" pgdata | tr -d "[:space:]"))"
  if [ "$REMOVE_SOURCE" -eq 1 ]; then
    say "  removing source volume ${src}"
    docker volume rm "$src" >/dev/null
  fi
}

migrate_one() {
  local service=$1 volume_key=$2
  say "== ${service}"
  local named
  named="$(named_volume "$volume_key")"
  if [ -z "$named" ]; then
    say "  named volume ${PROJECT}_${volume_key} was not found; nothing to migrate"
    return 0
  fi
  say "  named volume: ${named}"
  if volume_has_pg "$named" pgdata && [ "$FORCE" -ne 1 ]; then
    say "  ${named}/pgdata already contains a cluster; leaving it in place"
    return 0
  fi
  # A manual mount fix may have left the cluster at the named volume root.
  if volume_has_pg "$named" "" && ! volume_has_pg "$named" pgdata; then
    say "  cluster is at the root of ${named}; moving it to pgdata/"
    if [ "$APPLY" -eq 1 ]; then
      docker run --rm -v "${named}:/v" --entrypoint /bin/sh "$POSTGRES_IMAGE" -c '
        set -eu
        mkdir -p /tmp/pgmove
        find /v -mindepth 1 -maxdepth 1 ! -name pgdata ! -name tmp-pgmove -exec cp -a {} /tmp/pgmove/ \;
        mkdir -p /v/pgdata
        cp -a /tmp/pgmove/. /v/pgdata/
        chown -R postgres:postgres /v/pgdata
      '
      say "  moved root cluster into pgdata/"
    else
      say "  dry-run: would move the root cluster into pgdata/"
    fi
    return 0
  fi
  local src="" name
  while IFS= read -r name; do
    [ -n "$name" ] || continue
    [ "$name" = "$named" ] && continue
    case " $USED_SOURCES " in
      *" $name "*) continue ;;
    esac
    if volume_has_pg "$name" ""; then
      src=$name
      break
    fi
  done < <(anonymous_candidates "$service")
  if [ -z "$src" ]; then
    say "  no anonymous volume with PG_VERSION found for ${service}"
    say "  if the container still exists, inspect it:"
    say "    docker inspect <container> --format '{{range .Mounts}}{{.Destination}} {{.Name}}{{\"\\n\"}}{{end}}'"
    return 0
  fi
  say "  anonymous source: ${src} (PG_VERSION $(volume_pg_version "$src" | tr -d '[:space:]'))"
  USED_SOURCES="${USED_SOURCES} ${src} "
  copy_cluster "$src" "$named"
}

USED_SOURCES=" "

say "project: ${PROJECT}"
say "image:   ${POSTGRES_IMAGE}"
if [ "$APPLY" -eq 1 ]; then
  say "mode:    apply"
  running="$(docker ps --format '{{.Names}}' | grep -E 'postgres' || true)"
  if [ -n "$running" ]; then
    say "refusing to copy while postgres containers are running:"
    printf '%s\n' "$running" | sed 's/^/  /'
    say "stop them first: docker compose down"
    exit 1
  fi
else
  say "mode:    dry-run (pass --apply to copy)"
fi

migrate_one netbox-postgres netbox-postgres-data
migrate_one insightengine-postgres insightengine-postgres-data
say "activepieces-postgres mounts /var/lib/postgresql/data directly; it is not migrated"
say "netdisco-postgres is PostgreSQL 18 with the named volume at /var/lib/postgresql; it is not migrated"
say "done"
