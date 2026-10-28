#!/usr/bin/env bash
# Upgrade an existing InsightEngine checkout.
#
#   ./scripts/upgrade.sh --dry-run
#   ./scripts/upgrade.sh --yes
#   ./scripts/upgrade.sh --self-test
#
# Fills missing .env secrets before any docker compose command, then stops
# containers by the compose project label and leaves them in place.
# --dry-run still runs the read-only steps: it prints the keys it would add
# without writing them, runs `docker compose config -q`, and runs
# scripts/migrate-pg-volumes.sh without --apply.
# Confirm before the copy and before start unless --yes or --dry-run.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=lib-compose-env.sh
. "$ROOT/scripts/lib-compose-env.sh"

DRY=0
YES=0
SELF_TEST=0
LOG="${UPGRADE_LOG:-}"
ENV_FILE="${UPGRADE_ENV_FILE:-$ROOT/.env}"
install_bin="${UPGRADE_INSTALL_BIN:-$ROOT/install.sh}"
migrate_bin="${UPGRADE_MIGRATE_BIN:-$ROOT/scripts/migrate-pg-volumes.sh}"
provision_bin="${UPGRADE_PROVISION_BIN:-$ROOT/scripts/provision-netbox-token.sh}"

usage() {
  sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --dry-run) DRY=1; shift ;;
    --yes) YES=1; shift ;;
    --self-test) SELF_TEST=1; shift ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

say() { printf '%s\n' "$*"; }

confirm() {
  local prompt=$1 ans
  if [ "$YES" -eq 1 ] || [ "$DRY" -eq 1 ]; then
    say "confirm: ${prompt} (auto)"
    return 0
  fi
  printf '%s [y/N] ' "$prompt"
  read -r ans || true
  case "$ans" in
    y|Y|yes|YES) ;;
    *) say "aborted"; exit 1 ;;
  esac
}

plan() {
  say "+ $*"
  if [ -n "$LOG" ]; then
    printf 'plan: %s\n' "$*" >> "$LOG"
  fi
  if [ "$DRY" -eq 1 ]; then
    return 0
  fi
  "$@"
}

run_readonly() {
  say "+ $*"
  if [ -n "$LOG" ]; then
    printf 'run: %s\n' "$*" >> "$LOG"
  fi
  "$@"
}

image_id() {
  docker image inspect -f '{{.Id}}' "$1" 2>/dev/null || printf '%s' missing
}

preview_backfill() {
  local key val missing=0
  say "env backfill preview (${ENV_FILE}):"
  while IFS= read -r key; do
    [ -n "$key" ] || continue
    val="$(env_file_value "$key" "$ENV_FILE")"
    if [ -z "$val" ]; then
      say "  would add ${key} (missing or empty; value is not printed)"
      missing=1
    fi
  done < <(backfill_secret_keys)
  if [ "$missing" -eq 0 ]; then
    say "  no required secrets are missing"
  fi
  if [ "$DRY" -eq 1 ]; then
    say "dry-run: .env was not modified"
  fi
}

run_compose_config() {
  say "+ docker compose config -q"
  if [ -n "$LOG" ]; then
    printf 'run: docker compose config -q\n' >> "$LOG"
  fi
  (
    compose_export_placeholders "$ENV_FILE"
    docker compose config -q
  )
}

stop_project_containers() {
  local project=$1 id
  local -a ids=()
  while IFS= read -r id; do
    [ -n "$id" ] || continue
    ids+=("$id")
  done < <(docker ps -q --filter "label=com.docker.compose.project=${project}")
  if [ "${#ids[@]}" -eq 0 ]; then
    say "no running containers labeled com.docker.compose.project=${project}"
    return 0
  fi
  say "stopping ${#ids[@]} container(s) for project ${project}"
  docker stop "${ids[@]}"
}

upgrade_self_test() {
  local tmp envfile before after out log dlog idfile
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  envfile="$tmp/old.env"
  printf '%s\n' "PUBLIC_HOST=example" "NETBOX_DB_PASSWORD=already-set" > "$envfile"
  before="$(cksum "$envfile")"
  idfile="$tmp/id"
  printf '%s' 'sha256:before' > "$idfile"
  cat > "$tmp/docker" <<'EOF'
#!/bin/bash
printf '%s\n' "$*" >> "$UPGRADE_DOCKER_LOG"
args=" $* "
case "$args" in
  *" build "*)
    printf '%s' 'sha256:after' > "$UPGRADE_IDFILE"
    exit 0
    ;;
  *" image "*)
    cat "$UPGRADE_IDFILE"
    exit 0
    ;;
  *" config "*)
    case "$args" in
      *" -q "*) exit 0 ;;
    esac
    printf '%s\n' '{"name":"insightengine"}'
    exit 0
    ;;
  *" ps "*)
    case "$args" in
      *" -q "*netbox*)
        printf '%s\n' 'cid-netbox'
        ;;
      *" -q "*com.docker.compose.project=insightengine*)
        printf '%s\n' 'cid-1'
        ;;
    esac
    exit 0
    ;;
  *" stop "*)
    exit 0
    ;;
  *" inspect "*)
    printf '%s\n' healthy
    exit 0
    ;;
esac
exit 0
EOF
  cat > "$tmp/install.sh" <<'EOF'
#!/bin/bash
printf 'called install %s\n' "$*" >> "$UPGRADE_DOCKER_LOG"
if [ ! -f "$UPGRADE_ENV_FILE" ]; then
  echo "missing env file" >&2
  exit 1
fi
printf '\n%s\n' 'NETBOX_SUPERUSER_API_KEY=generated-for-test' >> "$UPGRADE_ENV_FILE"
exit 0
EOF
  cat > "$tmp/migrate.sh" <<'EOF'
#!/bin/bash
printf 'called migrate %s\n' "$*" >> "$UPGRADE_DOCKER_LOG"
if [ "${1:-}" = "--apply" ]; then
  printf '%s\n' 'migrate apply'
  exit 0
fi
printf '%s\n' 'mapping: netbox anon-nb -> named/pgdata'
exit 0
EOF
  cat > "$tmp/provision.sh" <<'EOF'
#!/bin/bash
printf 'called provision %s\n' "$*" >> "$UPGRADE_DOCKER_LOG"
exit 0
EOF
  chmod +x "$tmp/docker" "$tmp/install.sh" "$tmp/migrate.sh" "$tmp/provision.sh"

  run_child() {
    local flow=$1 rc mock_path
    shift
    set +e
    # shellcheck disable=SC2031
    mock_path="$tmp:$PATH"
    env -u COMPOSE_PROJECT_NAME \
      UPGRADE_SELF_TEST_FLOW="$flow" \
      UPGRADE_ENV_FILE="$envfile" \
      UPGRADE_LOG="$log" \
      UPGRADE_DOCKER_LOG="$dlog" \
      UPGRADE_IDFILE="$idfile" \
      UPGRADE_INSTALL_BIN="$tmp/install.sh" \
      UPGRADE_MIGRATE_BIN="$tmp/migrate.sh" \
      UPGRADE_PROVISION_BIN="$tmp/provision.sh" \
      "PATH=${mock_path}" \
      bash "$ROOT/scripts/upgrade.sh" "$@" > "$out" 2>"$tmp/err"
    rc=$?
    set -e
    if [ "$rc" -ne 0 ]; then
      echo "upgrade ${flow} failed (exit ${rc})" >&2
      cat "$tmp/err" >&2
      cat "$out" >&2
      exit 1
    fi
  }

  log="$tmp/dry.log"
  dlog="$tmp/dry.docker"
  out="$tmp/dry.out"
  : > "$log"
  : > "$dlog"
  run_child dry --dry-run
  after="$(cksum "$envfile")"
  [ "$before" = "$after" ]
  grep -q 'would add NETBOX_SUPERUSER_API_KEY' "$out"
  if grep -q 'would add NETBOX_DB_PASSWORD' "$out"; then
    echo "preview listed a secret that already has a value" >&2
    exit 1
  fi
  grep -q 'dry-run: .env was not modified' "$out"
  grep -q 'compose project: insightengine' "$out"
  if grep -q 'compose project: workspace' "$out"; then
    echo "dry-run used the directory name as the compose project" >&2
    exit 1
  fi
  grep -q 'run: docker compose config -q' "$log"
  grep -q "run: $tmp/migrate.sh" "$log"
  if grep -q 'run: .*-apply' "$log"; then
    echo "dry-run executed migrate --apply" >&2
    exit 1
  fi
  if grep -q 'install.sh' "$log"; then
    echo "dry-run logged install.sh" >&2
    exit 1
  fi
  if grep -q 'called install' "$dlog"; then
    echo "dry-run executed the env backfill" >&2
    exit 1
  fi
  if grep -E -q '(^|[[:space:]])stop([[:space:]]|$)' "$dlog"; then
    echo "dry-run stopped containers" >&2
    exit 1
  fi
  if grep -E -q '(^|[[:space:]])build([[:space:]]|$)' "$dlog"; then
    echo "dry-run built images" >&2
    exit 1
  fi
  grep -q 'config --format json' "$dlog"
  grep -q 'config -q' "$dlog"
  python3 - "$out" <<'PY'
import pathlib, sys
text = pathlib.Path(sys.argv[1]).read_text()
add = text.find("would add NETBOX_SUPERUSER_API_KEY")
cfg = text.find("docker compose config -q")
mig = text.find("mapping: netbox")
if add < 0 or cfg < 0 or mig < 0 or not (add < cfg < mig):
    raise SystemExit("dry-run order want preview, then config -q, then migrate mapping; got positions %s %s %s" % (add, cfg, mig))
if "placeholder-not-a-secret" in text:
    raise SystemExit("placeholder leaked into the dry-run output")
PY
  if grep -q 'sha256:after' "$out"; then
    echo "dry-run changed the image id" >&2
    exit 1
  fi

  printf '%s\n' "PUBLIC_HOST=example" "NETBOX_DB_PASSWORD=already-set" > "$envfile"
  printf '%s' 'sha256:before' > "$idfile"
  log="$tmp/apply.log"
  dlog="$tmp/apply.docker"
  out="$tmp/apply.out"
  : > "$log"
  : > "$dlog"
  run_child apply --yes
  grep -q 'NETBOX_SUPERUSER_API_KEY=generated-for-test' "$envfile"
  grep -q 'compose project: insightengine' "$out"
  grep -q 'sha256:before -> sha256:after' "$out"
  python3 - "$log" "$tmp/install.sh" "$tmp/migrate.sh" <<'PY'
import pathlib, sys
log, install, migrate = sys.argv[1:]
lines = pathlib.Path(log).read_text().splitlines()
def at(prefix):
    for i, line in enumerate(lines, 1):
        if line.startswith(prefix):
            return i
    raise SystemExit("missing log line %s" % prefix)
install_at = at("run: " + install)
stop_at = at("run: docker stop label=com.docker.compose.project=insightengine")
config_at = at("run: docker compose config -q")
mig_at = at("run: " + migrate)
apply_at = at("run: " + migrate + " --apply")
build_at = at("plan: docker compose build")
up_at = at("plan: docker compose up -d")
order = [install_at, stop_at, config_at, mig_at, apply_at, build_at, up_at]
if order != sorted(order):
    raise SystemExit("apply order %s" % order)
if "docker compose stop" in pathlib.Path(log).read_text():
    raise SystemExit("apply used docker compose stop")
PY
  grep -q 'stop cid-1' "$dlog"
  grep -q 'called migrate --apply' "$dlog"
  if grep -q 'compose stop' "$dlog"; then
    echo "apply invoked docker compose stop" >&2
    exit 1
  fi
  echo "PASS  upgrade backfills before compose, dry-run stays read-only, stop uses the project label"
}

if [ "$SELF_TEST" -eq 1 ]; then
  upgrade_self_test
  exit 0
fi

say "=== InsightEngine upgrade ==="
if [ "$DRY" -eq 1 ]; then
  say "dry-run: missing secrets are listed and not written. Read-only compose config and the migration scan still run."
fi

say "1. Backfill missing secrets before any docker compose command."
preview_backfill
if [ "$DRY" -eq 0 ]; then
  run_readonly "$install_bin" --no-start
fi

say "2. Resolve the compose project, then stop by its container label."
PROJECT="$(resolve_compose_project "" "$ENV_FILE" "$ROOT" "$ROOT/docker-compose.yml")"
say "compose project: ${PROJECT}"
if [ "$DRY" -eq 1 ]; then
  say "dry-run: containers stay running. Current matches for com.docker.compose.project=${PROJECT}:"
  run_readonly docker ps --filter "label=com.docker.compose.project=${PROJECT}"
else
  say "stopping containers labeled com.docker.compose.project=${PROJECT}"
  if [ -n "$LOG" ]; then
    printf 'run: docker stop label=com.docker.compose.project=%s\n' "$PROJECT" >> "$LOG"
  fi
  stop_project_containers "$PROJECT"
fi

say "3. Check the compose file. Empty required variables are placeholders in this process only."
run_compose_config

say "4. Show which Postgres volume is NetBox and which is ie-config."
run_readonly "$migrate_bin"
if [ "$DRY" -eq 0 ]; then
  confirm "Copy those clusters into the named volumes? Sources are not modified."
  run_readonly "$migrate_bin" --apply
else
  say "dry-run: not running ${migrate_bin} --apply"
fi

say "5. Rebuild local images. pull_policy: never images are not pulled."
before="$(image_id insightengine/ie-config:local)"
plan docker compose build
if ! plan docker compose pull --ignore-buildable; then
  say "WARNING: docker compose pull --ignore-buildable returned non-zero."
  say "Local images are built above. If a remote image failed to pull, fix the network and re-run."
fi
after="$(image_id insightengine/ie-config:local)"
say "insightengine/ie-config:local image id ${before} -> ${after}"
if [ "$before" != "missing" ] && [ "$before" = "$after" ] && [ "$DRY" -eq 0 ]; then
  say "WARNING: ie-config image id did not change. Rebuild with 'docker compose build --no-cache ie-config' if this checkout should be in the image."
fi

say "6. Start the stack."
if [ "$DRY" -eq 0 ]; then
  confirm "Start the stack with docker compose up -d?"
fi
plan docker compose up -d

say "7. Wait until NetBox is healthy, then provision an API token if the current file does not work."
if [ "$DRY" -eq 1 ]; then
  say "+ wait for netbox healthy, then ${provision_bin} --apply"
  if [ -n "$LOG" ]; then
    printf 'plan: %s --apply\n' "$provision_bin" >> "$LOG"
  fi
else
  i=0
  state=""
  while [ "$i" -lt 60 ]; do
    cid="$(docker compose ps -q netbox 2>/dev/null || true)"
    if [ -n "$cid" ]; then
      state="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || true)"
    fi
    if [ "$state" = "healthy" ]; then
      break
    fi
    i=$((i + 1))
    # The self-test flow has no NetBox. Do not sleep the ten-minute wait.
    if [ -z "${UPGRADE_SELF_TEST_FLOW:-}" ]; then
      sleep 10
    fi
  done
  if [ "$state" != "healthy" ]; then
    say "NetBox is not healthy yet. After it is: ${provision_bin} --apply"
  else
    "$provision_bin" --apply || say "token provision did not complete; re-run ${provision_bin} --apply"
  fi
fi

say "8. Restart services that read the token or the new image."
plan docker compose restart ie-config prometheus
plan docker compose up -d --force-recreate --no-deps oxidized netbox-device-types

say "=== upgrade steps finished ==="
