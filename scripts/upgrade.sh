#!/usr/bin/env bash
# Upgrade an existing InsightEngine checkout in a safe order.
#
#   ./scripts/upgrade.sh --dry-run
#   ./scripts/upgrade.sh --yes
#
# Stops the stack with `docker compose stop` (not down) so Postgres containers
# can still be inspected, backfills .env, copies clusters only after the
# migration dry-run identifies them, rebuilds local images, then starts.
# Confirm before the copy and before start unless --yes or --dry-run.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DRY=0
YES=0
SELF_TEST=0
LOG="${UPGRADE_LOG:-}"

usage() {
  sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --dry-run) DRY=1; shift ;;
    --yes) YES=1; shift ;;
    --self-test) SELF_TEST=1; DRY=1; YES=1; shift ;;
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

run() {
  say "+ $*"
  if [ -n "$LOG" ]; then
    printf '%s\n' "$*" >> "$LOG"
  fi
  if [ "$DRY" -eq 1 ]; then
    # Self-test still runs the fake docker so image ids can change.
    if [ "$SELF_TEST" -eq 1 ] && [ "$1" = "docker" ]; then
      "$@"
    fi
    return 0
  fi
  "$@"
}

image_id() {
  docker image inspect -f '{{.Id}}' "$1" 2>/dev/null || printf '%s' missing
}

if [ "$SELF_TEST" -eq 1 ]; then
  fake="$(mktemp -d)"
  trap 'rm -rf "$fake"' EXIT
  idfile="$fake/id"
  printf '%s' 'sha256:before' > "$idfile"
  cat > "$fake/docker" <<'EOF'
#!/bin/sh
if [ "$1" = "compose" ] && [ "$2" = "build" ]; then
  printf '%s' 'sha256:after' > "$UPGRADE_IDFILE"
fi
if [ "$1" = "image" ] && [ "$2" = "inspect" ]; then
  cat "$UPGRADE_IDFILE"
  exit 0
fi
exit 0
EOF
  chmod +x "$fake/docker"
  export PATH="$fake:$PATH"
  export UPGRADE_IDFILE="$idfile"
  LOG="$fake/log"
  : > "$LOG"
fi

say "=== InsightEngine upgrade ==="
if [ "$DRY" -eq 1 ]; then
  say "dry-run: commands are printed and not executed"
fi

say "1. Stop containers without removing them (inspect can still see data volumes)."
say "   Do not use 'docker compose down' before the copy; down detaches the anonymous volumes."
run docker compose stop

say "2. Backfill missing secrets in .env (does not start the stack, does not replace existing secrets)."
run ./install.sh --no-start

say "3. Show which Postgres volume is NetBox and which is ie-config."
run ./scripts/migrate-pg-volumes.sh
confirm "Copy those clusters into the named volumes? Sources are not modified."
if [ "$DRY" -eq 0 ]; then
  ./scripts/migrate-pg-volumes.sh --apply
else
  say "+ ./scripts/migrate-pg-volumes.sh --apply"
  if [ -n "$LOG" ]; then printf '%s\n' "./scripts/migrate-pg-volumes.sh --apply" >> "$LOG"; fi
fi

say "4. Rebuild local images. pull_policy: never images are not pulled."
before="$(image_id insightengine/ie-config:local)"
run docker compose build
if ! run docker compose pull --ignore-buildable; then
  say "WARNING: docker compose pull --ignore-buildable returned non-zero."
  say "Local images are built above. If a remote image failed to pull, fix the network and re-run."
fi
after="$(image_id insightengine/ie-config:local)"
say "insightengine/ie-config:local image id ${before} -> ${after}"
if [ "$before" != "missing" ] && [ "$before" = "$after" ] && [ "$DRY" -eq 0 ]; then
  say "WARNING: ie-config image id did not change. Rebuild with 'docker compose build --no-cache ie-config' if this checkout should be in the image."
fi

say "5. Start the stack."
confirm "Start the stack with docker compose up -d?"
run docker compose up -d

say "6. Wait until NetBox is healthy, then provision an API token if the current file does not work."
if [ "$DRY" -eq 1 ]; then
  say "+ wait for netbox healthy, then ./scripts/provision-netbox-token.sh --apply"
  if [ -n "$LOG" ]; then printf '%s\n' "provision-netbox-token.sh --apply" >> "$LOG"; fi
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
    sleep 10
  done
  if [ "$state" != "healthy" ]; then
    say "NetBox is not healthy yet. After it is: ./scripts/provision-netbox-token.sh --apply"
  else
    ./scripts/provision-netbox-token.sh --apply || say "token provision did not complete; re-run ./scripts/provision-netbox-token.sh --apply"
  fi
fi

say "7. Restart services that read the token or the new image."
run docker compose restart ie-config prometheus
run docker compose up -d --force-recreate --no-deps oxidized netbox-device-types

if [ "$SELF_TEST" -eq 1 ]; then
  [ "$before" = "sha256:before" ]
  [ "$after" = "sha256:after" ]
  grep -q 'docker compose stop' "$LOG"
  grep -q './install.sh --no-start' "$LOG"
  grep -q './scripts/migrate-pg-volumes.sh$' "$LOG" || grep -q './scripts/migrate-pg-volumes.sh' "$LOG"
  grep -q './scripts/migrate-pg-volumes.sh --apply' "$LOG"
  grep -q 'docker compose build' "$LOG"
  grep -q 'docker compose up -d' "$LOG"
  grep -q 'provision-netbox-token.sh --apply' "$LOG"
  # build is recorded before up
  build_at="$(grep -n 'docker compose build' "$LOG" | head -n1 | cut -d: -f1)"
  up_at="$(grep -n 'docker compose up -d$' "$LOG" | head -n1 | cut -d: -f1)"
  mig_at="$(grep -n 'migrate-pg-volumes.sh --apply' "$LOG" | head -n1 | cut -d: -f1)"
  [ -n "$build_at" ] && [ -n "$up_at" ] && [ -n "$mig_at" ]
  [ "$mig_at" -lt "$build_at" ]
  [ "$build_at" -lt "$up_at" ]
  echo "PASS  upgrade order is stop, backfill, migrate, build, up; image id changes"
fi

say "=== upgrade steps finished ==="
