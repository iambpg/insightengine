#!/usr/bin/env bash
# Remove this InsightEngine install so a fresh ./install.sh can start over.
#
#   ./scripts/uninstall.sh
#   ./scripts/uninstall.sh --apply
#   ./scripts/uninstall.sh --apply --yes
#   ./scripts/uninstall.sh --backup-first --apply --yes
#   ./scripts/uninstall.sh --keep-images --keep-certs --keep-backups --apply --yes
#   ./scripts/uninstall.sh --files-only --apply --yes     (Docker unreachable, see docs)
#
# The default is a dry-run. It lists containers, networks, named and anonymous
# volumes for this compose project, local images, and installer files. Nothing
# is deleted. Real removal needs --apply and either --yes or an interactive
# confirmation (the client slug or the word DELETE).
#
# Only Docker objects labelled com.docker.compose.project for this project are
# removed, plus anonymous volumes still mounted by those containers (the
# old-layout Postgres data volumes). Other containers on the host are left.
# Git-tracked files and the repository itself are never deleted. Secrets are
# never printed.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=lib-compose-env.sh
. "$ROOT/scripts/lib-compose-env.sh"

APPLY=0
YES=0
KEEP_IMAGES=0
KEEP_CERTS=0
KEEP_BACKUPS=0
BACKUP_FIRST=0
FILES_ONLY=0
PROJECT_ARG=""

usage() {
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --apply) APPLY=1; shift ;;
    --yes) YES=1; shift ;;
    --dry-run) APPLY=0; shift ;;
    --keep-images) KEEP_IMAGES=1; shift ;;
    --keep-certs) KEEP_CERTS=1; shift ;;
    --keep-backups) KEEP_BACKUPS=1; shift ;;
    --backup-first) BACKUP_FIRST=1; shift ;;
    --files-only) FILES_ONLY=1; shift ;;
    --project)
      [ $# -ge 2 ] || { echo "--project needs a value" >&2; exit 2; }
      PROJECT_ARG="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

say() { printf '%s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

DOCKER_OK=0
DOCKER_WHY=""
if [ "$FILES_ONLY" = 1 ]; then
  DOCKER_WHY="--files-only"
elif ! command -v docker >/dev/null 2>&1; then
  DOCKER_WHY="the docker command was not found"
elif DOCKER_ERR="$(docker info 2>&1 >/dev/null)"; then
  DOCKER_OK=1
elif printf '%s' "$DOCKER_ERR" | grep -qi 'permission denied'; then
  DOCKER_WHY="this user cannot use the Docker socket (run with sudo)"
else
  DOCKER_WHY="the Docker daemon is not running"
fi
if [ "$DOCKER_OK" != 1 ] && [ "$FILES_ONLY" != 1 ]; then
  warn "Docker is not usable: ${DOCKER_WHY}. Containers, networks, volumes, and images are not listed or changed."
fi

if [ "$DOCKER_OK" = 1 ]; then
  PROJECT="$(resolve_compose_project "$PROJECT_ARG" "$ROOT/.env" "$ROOT" "$ROOT/docker-compose.yml")"
else
  PROJECT="$(compose_file_project_name "$ROOT/docker-compose.yml" || true)"
  [ -n "$PROJECT" ] || PROJECT="insightengine"
fi

PUBLIC_HOST="$(env_file_value PUBLIC_HOST "$ROOT/.env")"
CLIENT_SLUG="$(env_file_value CLIENT_SLUG "$ROOT/.env")"

is_tracked() {
  git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 || return 1
  git -C "$ROOT" ls-files --error-unmatch -- "$1" >/dev/null 2>&1
}

is_local_image() {
  case "$1" in
    insightengine/*:local|insightengine-ui:local) return 0 ;;
    *) return 1 ;;
  esac
}

is_backup_path() {
  case "$1" in
    data/migration/*|migration/imported/*|*.dump) return 0 ;;
    *) return 1 ;;
  esac
}

safe_rel() {
  case "$1" in
    ""|..|../*|*/../*|*/..) return 1 ;;
    *) return 0 ;;
  esac
}

declare -a CONTAINERS=() VOLUMES=() NETWORKS=() IMAGES=() FILES=() KEPT=()
declare -A VOL_SEEN=()

add_volume() {
  local name=$1
  safe_rel "$name" || return 0
  [ -n "$name" ] || return 0
  if [ -n "${VOL_SEEN[$name]:-}" ]; then
    return 0
  fi
  VOL_SEEN["$name"]=1
  VOLUMES+=("$name")
}

collect_docker() {
  [ "$DOCKER_OK" = 1 ] || return 0
  local line id dest name vtype
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    CONTAINERS+=("$line")
    id="${line%% *}"
    while IFS='|' read -r vtype name dest; do
      [ "$vtype" = "volume" ] || continue
      [ -n "$name" ] || continue
      add_volume "$name"
    done < <(docker inspect -f '{{range .Mounts}}{{.Type}}|{{.Name}}|{{.Destination}}{{"\n"}}{{end}}' "$id" 2>/dev/null || true)
  done < <(docker ps -a --filter "label=com.docker.compose.project=${PROJECT}" --format '{{.ID}} {{.Label "com.docker.compose.service"}}')

  while IFS= read -r name; do
    [ -n "$name" ] || continue
    add_volume "$name"
  done < <(docker volume ls -q --filter "label=com.docker.compose.project=${PROJECT}" 2>/dev/null || true)

  while IFS= read -r name; do
    [ -n "$name" ] || continue
    case "$name" in
      bridge|host|none) continue ;;
    esac
    NETWORKS+=("$name")
  done < <(docker network ls --filter "label=com.docker.compose.project=${PROJECT}" --format '{{.Name}}' 2>/dev/null || true)

  if [ "$KEEP_IMAGES" = 0 ]; then
    while IFS= read -r name; do
      [ -n "$name" ] || continue
      is_local_image "$name" || continue
      IMAGES+=("$name")
    done < <(docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null || true)
  fi
}

consider_file() {
  local rel=$1
  safe_rel "$rel" || return 0
  [ -e "$ROOT/$rel" ] || [ -L "$ROOT/$rel" ] || return 0
  if is_tracked "$rel"; then
    KEPT+=("$rel")
    return 0
  fi
  if [ "$KEEP_CERTS" = 1 ]; then
    case "$rel" in
      certs|certs/*) KEPT+=("$rel"); return 0 ;;
    esac
  fi
  if [ "$KEEP_BACKUPS" = 1 ] && is_backup_path "$rel"; then
    KEPT+=("$rel")
    return 0
  fi
  FILES+=("$rel")
}

consider_tree() {
  local rel=$1 path relpath
  [ -d "$ROOT/$rel" ] || return 0
  while IFS= read -r -d '' path; do
    relpath="${path#"$ROOT"/}"
    [ -d "$path" ] && [ ! -L "$path" ] && continue
    consider_file "$relpath"
  done < <(find "$ROOT/$rel" -mindepth 1 -print0 2>/dev/null || true)
}

declare -a UNREADABLE=()

collect_files() {
  local path dir
  for dir in certs secrets data migration config/netdisco/nd-site-local; do
    [ -d "$ROOT/$dir" ] || continue
    while IFS= read -r -d '' path; do
      UNREADABLE+=("${path#"$ROOT"/}")
    done < <(find "$ROOT/$dir" -type d \( ! -readable -o ! -executable \) -print0 2>/dev/null || true)
  done
  consider_file .env
  consider_file .install-started
  consider_file migration/migrate.conf
  consider_tree certs
  consider_tree secrets
  consider_tree data
  consider_tree migration/imported
  consider_tree config/netdisco/nd-site-local
}

print_list() {
  local title=$1
  shift
  say "$title"
  if [ "$#" -eq 0 ]; then
    say "  (none)"
    return 0
  fi
  local item
  for item in "$@"; do
    say "  $item"
  done
}

print_plan() {
  if [ "$APPLY" = 1 ]; then
    say "=== InsightEngine uninstall ==="
  else
    say "=== InsightEngine uninstall (dry-run) ==="
  fi
  say "compose project: ${PROJECT}"
  say "Only Docker objects with com.docker.compose.project=${PROJECT} are included, plus volumes those containers mount."
  print_list "containers:" ${CONTAINERS[@]+"${CONTAINERS[@]}"}
  print_list "volumes:" ${VOLUMES[@]+"${VOLUMES[@]}"}
  print_list "networks:" ${NETWORKS[@]+"${NETWORKS[@]}"}
  if [ "$KEEP_IMAGES" = 1 ]; then
    say "images: kept (--keep-images)"
  else
    print_list "images:" ${IMAGES[@]+"${IMAGES[@]}"}
  fi
  print_list "files:" ${FILES[@]+"${FILES[@]}"}
  print_list "kept:" ${KEPT[@]+"${KEPT[@]}"}
  if [ "${#UNREADABLE[@]}" -gt 0 ]; then
    warn "this user cannot read ${#UNREADABLE[@]} director(ies), so the file list is incomplete (run with sudo):"
    print_list "unreadable:" "${UNREADABLE[@]}" >&2
  fi
  if [ "$BACKUP_FIRST" = 1 ]; then
    say "backup: NetBox and ie_config dumps would be written outside the repository before removal"
  fi
}

confirm_destroy() {
  local ans
  if [ "$YES" = 1 ]; then
    say "confirmation: --yes"
    return 0
  fi
  if [ ! -t 0 ]; then
    die "refusing to remove without --yes or an interactive confirmation (type the client slug or DELETE)"
  fi
  if [ -n "$CLIENT_SLUG" ]; then
    printf 'Type the client slug (%s) or DELETE to remove this install: ' "$CLIENT_SLUG" >&2
  else
    printf 'Type DELETE to remove this install: ' >&2
  fi
  read -r ans || true
  if [ "$ans" = "DELETE" ] || { [ -n "$CLIENT_SLUG" ] && [ "$ans" = "$CLIENT_SLUG" ]; }; then
    return 0
  fi
  die "confirmation did not match; nothing was removed"
}

backup_one() {
  local service=$1 dbname=$2 outfile=$3 cid status
  cid=""
  while IFS= read -r cid; do
    [ -n "$cid" ] && break
  done < <(docker ps -aq --filter "label=com.docker.compose.project=${PROJECT}" --filter "label=com.docker.compose.service=${service}" || true)
  [ -n "$cid" ] || die "backup failed: no ${service} container in project ${PROJECT}; nothing was removed"
  status="$(docker inspect -f '{{.State.Status}}' "$cid" 2>/dev/null || true)"
  if [ "$status" != "running" ]; then
    docker start "$cid" >/dev/null || die "backup failed: could not start ${service}; nothing was removed"
  fi
  # The container already has POSTGRES_USER. The password is not put on this command line.
  if [ "$dbname" = "POSTGRES_DB" ]; then
    docker exec "$cid" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > "$outfile" \
      || { rm -f "$outfile"; die "backup failed: pg_dump ${service}; nothing was removed"; }
  else
    docker exec "$cid" sh -c 'pg_dump -U "$POSTGRES_USER" -d ie_config' > "$outfile" \
      || { rm -f "$outfile"; die "backup failed: pg_dump ${service} ie_config; nothing was removed"; }
  fi
  [ -s "$outfile" ] || { rm -f "$outfile"; die "backup failed: ${outfile} is empty; nothing was removed"; }
  say "backed up ${service} to ${outfile}"
}

run_backup() {
  [ "$DOCKER_OK" = 1 ] || die "--backup-first needs a running Docker daemon; nothing was removed"
  local dest root stamp
  root="${UNINSTALL_BACKUP_DIR:-${HOME:-/var/tmp}/insightengine-backups}"
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  dest="${root}/uninstall-${stamp}"
  case "$dest" in
    "$ROOT"|"$ROOT"/*) die "backup directory must be outside the repository" ;;
  esac
  # The dumps hold every credential stored in the databases: owner-only.
  umask 077
  mkdir -p "$dest" || die "backup failed: cannot create ${dest}; nothing was removed"
  backup_one netbox-postgres POSTGRES_DB "$dest/netbox.sql"
  backup_one insightengine-postgres ie_config "$dest/ie_config.sql"
  say "backups are in ${dest} (owner-only; they contain credentials, copy them somewhere safe)"
}

FAILED_VOLUMES=0
FAILED_OTHER=0

remove_docker() {
  [ "$DOCKER_OK" = 1 ] || return 0
  local id name
  if [ "${#CONTAINERS[@]}" -gt 0 ]; then
    local -a ids=()
    for id in "${CONTAINERS[@]}"; do
      ids+=("${id%% *}")
    done
    docker rm -f "${ids[@]}" >/dev/null || die "could not remove the containers; nothing else was removed"
    say "removed ${#ids[@]} container(s)"
  fi
  # One object at a time: a volume or image used by something outside this project must
  # not stop the rest of the wipe.
  for name in ${VOLUMES[@]+"${VOLUMES[@]}"}; do
    docker volume rm "$name" >/dev/null 2>&1 || { warn "could not remove volume ${name} (in use by another container?)"; FAILED_VOLUMES=$((FAILED_VOLUMES + 1)); }
  done
  [ "${#VOLUMES[@]}" -eq 0 ] || say "removed $(( ${#VOLUMES[@]} - FAILED_VOLUMES )) of ${#VOLUMES[@]} volume(s)"
  for name in ${NETWORKS[@]+"${NETWORKS[@]}"}; do
    docker network rm "$name" >/dev/null 2>&1 || { warn "could not remove network ${name} (still has endpoints?)"; FAILED_OTHER=$((FAILED_OTHER + 1)); }
  done
  if [ "$KEEP_IMAGES" = 0 ]; then
    for name in ${IMAGES[@]+"${IMAGES[@]}"}; do
      docker rmi "$name" >/dev/null 2>&1 || { warn "could not remove image ${name} (in use?)"; FAILED_OTHER=$((FAILED_OTHER + 1)); }
    done
  fi
}

remove_files() {
  local rel path
  if [ "${#FILES[@]}" -eq 0 ]; then
    return 0
  fi
  for rel in "${FILES[@]}"; do
    path="$ROOT/$rel"
    if [ -L "$path" ] || [ -e "$path" ]; then
      rm -f "$path"
    fi
  done
  local dir
  for dir in config/netdisco/nd-site-local migration/imported data secrets certs; do
    [ -d "$ROOT/$dir" ] || continue
    find "$ROOT/$dir" -depth -type d -empty -exec rmdir {} \; 2>/dev/null || true
  done
  if [ "${#FILES[@]}" -gt 0 ]; then
    say "removed ${#FILES[@]} file(s)"
  fi
}

print_next() {
  if [ -n "$PUBLIC_HOST" ]; then
    say "next: sudo ./install.sh --public-host ${PUBLIC_HOST}"
  else
    say "next: sudo ./install.sh --public-host <host>"
    say "PUBLIC_HOST was not set in .env; substitute the host name you want on the certificate."
  fi
}

collect_docker
collect_files
print_plan

if [ "$APPLY" != 1 ]; then
  print_next
  say "dry-run: nothing was removed. Re-run with --apply and type the client slug or DELETE, or pass --apply --yes."
  exit 0
fi

if [ "$DOCKER_OK" != 1 ] && [ "$FILES_ONLY" != 1 ]; then
  die "Docker is not usable (${DOCKER_WHY}). Deleting only the files would leave volumes that still hold the old database passwords, and a fresh install would not start. Fix Docker (or run with sudo) and retry, or pass --files-only to delete just the files; nothing was removed"
fi
if [ "${#UNREADABLE[@]}" -gt 0 ]; then
  die "this user cannot read ${#UNREADABLE[@]} director(ies) of the install (re-run with sudo); nothing was removed"
fi
for rel in ${FILES[@]+"${FILES[@]}"}; do
  if [ ! -w "$(dirname "$ROOT/$rel")" ]; then
    die "cannot delete ${rel}: its directory is not writable by this user (re-run with sudo); nothing was removed"
  fi
done
confirm_destroy
if [ "$BACKUP_FIRST" = 1 ]; then
  run_backup
fi
remove_docker
if [ "$FAILED_VOLUMES" -gt 0 ]; then
  die "${FAILED_VOLUMES} volume(s) could not be removed, so the files were kept: a fresh install would reuse the old database volumes with new passwords. Remove what is using them and run this script again"
fi
remove_files

say "=== removed ==="
print_list "containers:" ${CONTAINERS[@]+"${CONTAINERS[@]}"}
print_list "volumes:" ${VOLUMES[@]+"${VOLUMES[@]}"}
print_list "networks:" ${NETWORKS[@]+"${NETWORKS[@]}"}
if [ "$KEEP_IMAGES" = 1 ]; then
  say "images: kept (--keep-images)"
else
  print_list "images:" ${IMAGES[@]+"${IMAGES[@]}"}
fi
print_list "files:" ${FILES[@]+"${FILES[@]}"}
say "=== remains ==="
print_list "kept files:" ${KEPT[@]+"${KEPT[@]}"}
say "repository: ${ROOT} (not deleted)"
say "Docker resources that are not labelled com.docker.compose.project=${PROJECT} were not removed."
if [ "$DOCKER_OK" != 1 ]; then
  warn "Docker was not usable, so containers, networks, volumes, and images were not changed (--files-only)."
fi
print_next
[ "$FAILED_OTHER" -eq 0 ] || { warn "${FAILED_OTHER} network(s) or image(s) could not be removed; see above"; exit 1; }
