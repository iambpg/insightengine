#!/usr/bin/env bash
# Copy Postgres data out of anonymous volumes left by the old compose mount.
#
# postgres:17.9 keeps the cluster in /var/lib/postgresql/data (the image VOLUME).
# Older compose files mounted the named volume at /var/lib/postgresql, so Docker
# stored the real cluster in an anonymous volume. `docker compose down` orphans
# that volume. The anonymous volume label is only com.docker.volume.anonymous,
# so the volume name is not a safe way to tell NetBox from ie-config.
#
# This script:
#   1. If the postgres containers still exist (docker compose stop, not down),
#      reads the volume mounted at /var/lib/postgresql/data from docker inspect.
#   2. Otherwise reads each candidate's system catalogs (read-only) and keeps a
#      volume only when it uniquely contains the netbox or ie_config database.
#   3. Refuses to copy when a volume cannot be identified, when two volumes
#      match the same service, or when catalogs contradict the mapping.
# Source volumes are mounted read-only and are never deleted or modified.
#
#   ./scripts/migrate-pg-volumes.sh
#   ./scripts/migrate-pg-volumes.sh --apply
#   ./scripts/migrate-pg-volumes.sh --map netbox=<volume>,insightengine=<volume>
#   ./scripts/migrate-pg-volumes.sh --self-test
#
# Safest path if you have not run `docker compose down` yet:
#   docker compose stop
#   ./scripts/migrate-pg-volumes.sh
#   ./scripts/migrate-pg-volumes.sh --apply
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
MATCH="$ROOT/scripts/migrate-pg-match.py"

APPLY=0
FORCE=0
SELF_TEST=0
MAP_RAW=""
PROJECT="${COMPOSE_PROJECT_NAME:-}"
POSTGRES_IMAGE="${POSTGRES_IMAGE:-}"

usage() {
  sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --apply) APPLY=1; shift ;;
    --dry-run) APPLY=0; shift ;;
    --force) FORCE=1; shift ;;
    --remove-source)
      echo "refusing --remove-source: source volumes are never deleted or modified" >&2
      exit 2
      ;;
    --project) PROJECT="${2:-}"; shift 2 ;;
    --image) POSTGRES_IMAGE="${2:-}"; shift 2 ;;
    --map) MAP_RAW="${2:-}"; shift 2 ;;
    --self-test) SELF_TEST=1; shift ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

env_file_value() {
  local key=$1 file=${2:-.env} line
  [ -f "$file" ] || return 0
  line="$(grep -E "^${key}=" "$file" | tail -n1 || true)"
  line="${line#*=}"
  line="${line#\'}"
  line="${line%\'}"
  printf '%s' "$line"
}

if [ "$SELF_TEST" -eq 1 ]; then
  tmp="$(mktemp -d)"
  printf "%s\n" "COMPOSE_PROJECT_NAME='from-dotenv'" > "$tmp/.env"
  got="$(env_file_value COMPOSE_PROJECT_NAME "$tmp/.env")"
  rm -rf "$tmp"
  [ "$got" = "from-dotenv" ]
  python3 "$MATCH" --self-test
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is not available; nothing was changed" >&2
  exit 1
fi
if [ -z "$POSTGRES_IMAGE" ]; then
  POSTGRES_IMAGE="$(env_file_value POSTGRES_IMAGE)"
fi
if [ -z "$POSTGRES_IMAGE" ]; then
  POSTGRES_IMAGE="postgres:17.9"
fi

if [ -z "$PROJECT" ]; then
  PROJECT="$(env_file_value COMPOSE_PROJECT_NAME)"
fi
if [ -z "$PROJECT" ]; then
  PROJECT="$(basename "$ROOT" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9')"
  [ -n "$PROJECT" ] || PROJECT="insightengine"
fi

say() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

volume_exists() {
  docker volume inspect "$1" >/dev/null 2>&1
}

named_volume() {
  local volume_key=$1 candidate found
  candidate="${PROJECT}_${volume_key}"
  if volume_exists "$candidate"; then
    printf '%s' "$candidate"
    return 0
  fi
  found="$(docker volume ls --format '{{.Name}}' | grep -E "(^|_)${volume_key}$" | head -n1 || true)"
  printf '%s' "$found"
}

# Print "id<TAB>container-service" for a data volume still attached to a container.
# container-service is netbox or insightengine. Empty container field if the mount
# is the named volume (new layout) rather than an anonymous data volume.
container_sources() {
  local service=$1 dest name vtype
  # shellcheck disable=SC2046
  docker ps -aq --filter "label=com.docker.compose.service=${service}" --filter "label=com.docker.compose.project=${PROJECT}" 2>/dev/null \
    | while IFS= read -r id; do
        [ -n "$id" ] || continue
        docker inspect -f '{{range .Mounts}}{{.Destination}}|{{.Name}}|{{.Type}}{{"\n"}}{{end}}' "$id" 2>/dev/null || true
      done | while IFS='|' read -r dest name vtype; do
        [ "$vtype" = "volume" ] || continue
        [ "$dest" = "/var/lib/postgresql/data" ] || continue
        case "$service" in
          netbox-postgres) printf '%s\tnetbox\n' "$name" ;;
          insightengine-postgres) printf '%s\tinsightengine\n' "$name" ;;
        esac
      done
}

describe_volume() {
  local vol=$1
  docker run --rm -v "${vol}:/v:ro" --entrypoint /bin/sh "$POSTGRES_IMAGE" -c '
    set -eu
    pv=$(cat /v/PG_VERSION 2>/dev/null || echo missing)
    bytes=$(du -sb /v 2>/dev/null | awk "{print \$1}")
    mtime=$(stat -c %y /v/PG_VERSION 2>/dev/null || echo unknown)
    names=$(grep -a -h -o -w -E "netbox|ie_config|insightengine|netdisco|telegraf_data|activepieces_data|postgres|template0|template1" /v/global/[0-9]* 2>/dev/null | sort -u | tr "\n" " " || true)
    printf "pg_version=%s\nbytes=%s\nmtime=%s\nnames=%s\n" "$pv" "${bytes:-0}" "$mtime" "$names"
  '
}

parse_map() {
  local raw=$1 piece dest vol
  [ -n "$raw" ] || return 0
  printf '%s' "$raw" | tr ',' '\n' | while IFS= read -r piece; do
    [ -n "$piece" ] || continue
    dest="${piece%%=*}"
    vol="${piece#*=}"
    case "$dest" in
      netbox|insightengine) ;;
      *) die "--map destination must be netbox or insightengine (got ${dest})" ;;
    esac
    if [ -z "$vol" ] || [ "$vol" = "$piece" ]; then
      die "--map entry must look like netbox=<volume>"
    fi
    printf '%s\t%s\n' "$dest" "$vol"
  done
}

dest_has_cluster() {
  docker run --rm -v "$1":/v:ro --entrypoint /bin/sh "$POSTGRES_IMAGE" -c 'test -f /v/pgdata/PG_VERSION' >/dev/null 2>&1
}

copy_cluster() {
  local src=$1 dest=$2
  if dest_has_cluster "$dest" && [ "$FORCE" -ne 1 ]; then
    say "  skip: ${dest}/pgdata already has a cluster (source ${src} not touched; --force keeps a pgdata.bak copy)"
    return 0
  fi
  if [ "$APPLY" -ne 1 ]; then
    say "  dry-run: would copy ${src} -> ${dest}/pgdata (source stays read-only)"
    return 0
  fi
  say "  copying ${src} -> ${dest}/pgdata (source mounted read-only)"
  docker run --rm \
    -v "${src}:/from:ro" \
    -v "${dest}:/to" \
    --entrypoint /bin/sh "$POSTGRES_IMAGE" \
    -c 'set -eu
      if [ ! -f /from/PG_VERSION ]; then echo "source has no PG_VERSION" >&2; exit 1; fi
      if [ -d /to/pgdata ] && [ -f /to/pgdata/PG_VERSION ]; then
        stamp=$(date -u +%Y%m%dT%H%M%SZ)
        mv /to/pgdata "/to/pgdata.bak.${stamp}"
      fi
      mkdir -p /to/pgdata
      cp -a /from/. /to/pgdata/
      chown -R postgres:postgres /to/pgdata
      test -f /to/pgdata/PG_VERSION
    '
  say "  copied. Source volume ${src} was not modified."
}

say "project: ${PROJECT}"
say "image:   ${POSTGRES_IMAGE}"
say "Sources are never deleted or modified. Identification is by database/role catalogs, or by a stopped container mount."
if [ "$APPLY" -eq 1 ]; then
  say "mode:    apply"
  running="$(docker ps --filter "label=com.docker.compose.project=${PROJECT}" --filter "label=com.docker.compose.service=netbox-postgres" --filter "status=running" -q || true)"
  running="${running}$(docker ps --filter "label=com.docker.compose.project=${PROJECT}" --filter "label=com.docker.compose.service=insightengine-postgres" --filter "status=running" -q || true)"
  if [ -n "$running" ]; then
    die "postgres containers are still running. Use 'docker compose stop' (not down) so inspect can see the data volumes, then re-run."
  fi
else
  say "mode:    dry-run (pass --apply to copy)"
fi

NB_VOL="$(named_volume netbox-postgres-data)"
IE_VOL="$(named_volume insightengine-postgres-data)"
[ -n "$NB_VOL" ] || die "named volume for netbox-postgres-data was not found (project ${PROJECT})"
[ -n "$IE_VOL" ] || die "named volume for insightengine-postgres-data was not found (project ${PROJECT})"
say "destination netbox:        ${NB_VOL}"
say "destination insightengine: ${IE_VOL}"

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

# Container mounts first.
: > "$WORKDIR/containers.tsv"
container_sources netbox-postgres >> "$WORKDIR/containers.tsv" || true
container_sources insightengine-postgres >> "$WORKDIR/containers.tsv" || true

# Every anonymous volume plus any container-attached data volume.
: > "$WORKDIR/candidates.txt"
if [ -s "$WORKDIR/containers.tsv" ]; then
  say "stopped containers still exist; using docker inspect mounts at /var/lib/postgresql/data"
  awk -F '\t' 'NF { print $1 }' "$WORKDIR/containers.tsv" | sort -u >> "$WORKDIR/candidates.txt"
else
  say "no postgres containers to inspect; identifying orphaned volumes by catalog contents"
  docker volume ls -q | while IFS= read -r name; do
    [ -n "$name" ] || continue
    printf '%s' "$name" | grep -Eq '^[0-9a-f]{64}$' || continue
    printf '%s\n' "$name"
  done >> "$WORKDIR/candidates.txt"
fi

export MIGRATE_ROOT="$ROOT"
export MIGRATE_IMAGE="$POSTGRES_IMAGE"
export MIGRATE_NB_VOL="$NB_VOL"
export MIGRATE_IE_VOL="$IE_VOL"
MIGRATE_MAP_LINES="$(parse_map "$MAP_RAW")"
export MIGRATE_MAP_LINES

python3 - "$WORKDIR" <<'PY'
import json, os, subprocess, sys
work = sys.argv[1]
image = os.environ["MIGRATE_IMAGE"]
nb = os.environ["MIGRATE_NB_VOL"]
ie = os.environ["MIGRATE_IE_VOL"]
explicit = {}
for line in os.environ.get("MIGRATE_MAP_LINES", "").splitlines():
    if not line.strip():
        continue
    dest, vol = line.split("\t", 1)
    explicit[dest] = vol
container = {}
path = os.path.join(work, "containers.tsv")
if os.path.isfile(path):
    for line in open(path, encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) == 2 and parts[0] and parts[1]:
            container[parts[0]] = parts[1]
names = []
seen = set()
cand = os.path.join(work, "candidates.txt")
if os.path.isfile(cand):
    for line in open(cand, encoding="utf-8"):
        name = line.strip()
        if name and name not in seen and name not in (nb, ie):
            seen.add(name)
            names.append(name)
for vol in explicit.values():
    if vol not in seen and vol not in (nb, ie):
        seen.add(vol)
        names.append(vol)
script = r'''set -eu
pv=$(cat /v/PG_VERSION 2>/dev/null || echo missing)
bytes=$(du -sb /v 2>/dev/null | awk '{print $1}')
mtime=$(stat -c %y /v/PG_VERSION 2>/dev/null || echo unknown)
names=$(grep -a -h -o -w -E 'netbox|ie_config|insightengine|netdisco|telegraf_data|activepieces_data|postgres|template0|template1' /v/global/[0-9]* /v/global/[0-9]*_[0-9]* 2>/dev/null | sort -u | tr '\n' ' ' || true)
printf 'pg_version=%s\nbytes=%s\nmtime=%s\nnames=%s\n' "$pv" "${bytes:-0}" "$mtime" "$names"
'''
volumes = []
for name in names:
    proc = subprocess.run(
        ["docker", "run", "--rm", "-v", "%s:/v:ro" % name, "--entrypoint", "/bin/sh", image, "-c", script],
        check=False, capture_output=True, text=True,
    )
    info = {"pg_version": "missing", "bytes": "0", "mtime": "unknown", "names": ""}
    if proc.returncode != 0:
        err = (proc.stderr or "describe failed").strip().splitlines()
        info["error"] = err[-1] if err else "describe failed"
    else:
        for line in proc.stdout.splitlines():
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            info[key] = val.strip()
    if info.get("pg_version") in ("", "missing"):
        continue
    tokens = [part for part in info.get("names", "").split() if part]
    volumes.append({
        "id": name,
        "databases": tokens,
        "roles": tokens,
        "bytes": int(info.get("bytes") or 0),
        "mtime": info.get("mtime") or "unknown",
        "pg_version": info.get("pg_version") or "",
        "container": container.get(name, ""),
    })
with open(os.path.join(work, "volumes.json"), "w", encoding="utf-8") as fh:
    json.dump({"volumes": volumes, "map": explicit}, fh)
PY

say "catalog scan (read-only):"
python3 - "$WORKDIR/volumes.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
rows = data.get("volumes") or []
if not rows:
    print("  (no postgres clusters found outside the named destination volumes)")
for row in rows:
    names = ", ".join(row.get("databases") or []) or "(none)"
    via = row.get("container") or "content"
    print("  volume %s" % row["id"])
    print("    pg_version=%s bytes=%s mtime=%s" % (row.get("pg_version"), row.get("bytes"), row.get("mtime")))
    print("    catalog names: %s" % names)
    print("    container mount: %s" % (row.get("container") or "(containers gone)"))
    print("    via: %s" % via)
PY

set +e
pairs="$(python3 "$MATCH" < "$WORKDIR/volumes.json" 2>"$WORKDIR/match.err")"
match_rc=$?
set -e
if [ "$match_rc" -ne 0 ]; then
  cat "$WORKDIR/match.err" >&2
  die "nothing was copied"
fi
if [ -z "$pairs" ]; then
  say "no netbox or ie-config cluster needs copying"
  exit 0
fi

say "mapping:"
while IFS="$(printf '\t')" read -r dest src; do
  [ -n "$dest" ] || continue
  case "$dest" in
    netbox) target="$NB_VOL" ;;
    insightengine) target="$IE_VOL" ;;
    *) die "matcher returned unknown destination ${dest}" ;;
  esac
  say "  ${dest}: ${src} -> ${target}/pgdata"
  copy_cluster "$src" "$target"
done <<EOF
$pairs
EOF

say "activepieces-postgres is already mounted at /var/lib/postgresql/data; it is not migrated"
say "netdisco-postgres is PostgreSQL 18 at /var/lib/postgresql; a netdisco catalog is ignored"
say "done"
