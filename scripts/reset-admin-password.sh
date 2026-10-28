#!/usr/bin/env bash
# Reset an ie-config user's password. Root only.
#
#   sudo ./scripts/reset-admin-password.sh
#   sudo ./scripts/reset-admin-password.sh --email admin@example.com
#   sudo ./scripts/reset-admin-password.sh --self-test
#
# The password is read with `read -s` on a terminal, or from stdin otherwise.
# It is not printed, not written to the audit detail, and not passed as a
# docker argument. The container is the compose service ie-config in this
# project (container name ie-config; it is not suffixed with CLIENT_SLUG).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=lib-compose-env.sh
. "$ROOT/scripts/lib-compose-env.sh"

EMAIL=""
SELF_TEST=0

usage() {
  sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --self-test) SELF_TEST=1; shift ;;
    --email)
      [ $# -ge 2 ] || { echo "reset-admin-password: --email needs an address" >&2; exit 2; }
      EMAIL="$2"
      shift 2
      ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

say() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

find_ie_config() {
  local project=$1 cid slug
  cid="$(
    docker ps -aq \
      --filter "label=com.docker.compose.project=${project}" \
      --filter "label=com.docker.compose.service=ie-config" \
      | awk 'NF { print; exit }'
  )"
  if [ -n "$cid" ]; then
    printf '%s' "$cid"
    return 0
  fi
  # container_name in docker-compose.yml is ie-config, not ie-config-$CLIENT_SLUG.
  cid="$(docker ps -aq --filter 'name=^ie-config$' | awk 'NF { print; exit }')"
  if [ -n "$cid" ]; then
    printf '%s' "$cid"
    return 0
  fi
  slug="$(env_file_value CLIENT_SLUG "$ROOT/.env")"
  if [ -n "$slug" ]; then
    cid="$(docker ps -aq --filter "name=^ie-config-${slug}$" | awk 'NF { print; exit }')"
  fi
  printf '%s' "$cid"
}

read_password() {
  local password=""
  if [ -t 0 ]; then
    printf 'New password (not echoed): ' >&2
    read -r -s password || true
    printf '\n' >&2
  else
    IFS= read -r password || true
  fi
  printf '%s' "$password"
}

run_reset() {
  local project cid
  if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
    die "Docker is not running, so ie-config cannot be reset from here"
  fi
  project="$(resolve_compose_project "" "$ROOT/.env" "$ROOT" "$ROOT/docker-compose.yml")"
  cid="$(find_ie_config "$project")"
  if [ -z "$cid" ]; then
    die "no ie-config container in compose project ${project}. If no administrator exists yet, open /setup/."
  fi
  local password
  password="$(read_password)"
  # stdin of the container process only. Not an argument, so it is not in `ps`.
  if [ -n "$EMAIL" ]; then
    if ! printf '%s' "$password" | docker exec -i "$cid" python -m ie_config reset-admin --email "$EMAIL"; then
      unset password
      exit 1
    fi
  else
    if ! printf '%s' "$password" | docker exec -i "$cid" python -m ie_config reset-admin; then
      unset password
      exit 1
    fi
  fi
  unset password
}

if [ "$SELF_TEST" = 1 ]; then
  tmp="$(mktemp -d)"
  bin="$tmp/bin"
  log="$tmp/docker.log"
  secret='CorrectHorse1battery'
  mkdir -p "$bin" "$tmp/state"
  cat > "$bin/docker" <<'EOF'
#!/bin/bash
printf '%s\n' "$*" >> "$MOCK_LOG"
case "$1" in
  info) exit 0 ;;
  compose)
    printf '%s\n' '{"name":"insightengine"}'
    ;;
  ps)
    joined="$*"
    case "$joined" in
      *service=ie-config*) printf '%s\n' 'cid-ie-config' ;;
      *name=^ie-config$*) printf '%s\n' 'cid-ie-config' ;;
    esac
    ;;
  exec)
    cat > "$MOCK_DIR/stdin"
    case "$*" in
      *"$MOCK_SECRET"*)
        echo 'password appeared in docker arguments' >&2
        exit 3
        ;;
    esac
    printf '%s\n' 'password reset for admin@example.com'
    ;;
  *) exit 0 ;;
esac
EOF
  chmod +x "$bin/docker"
  : > "$log"
  # shellcheck disable=SC2031
  env -u COMPOSE_PROJECT_NAME \
    RESET_SKIP_ROOT=1 \
    "PATH=${bin}:${PATH}" \
    MOCK_LOG="$log" \
    MOCK_DIR="$tmp/state" \
    MOCK_SECRET="$secret" \
    bash "$0" --email admin@example.com >"$tmp/out" 2>"$tmp/err" <<<"$secret"
  grep -q 'password reset for admin@example.com' "$tmp/out"
  grep -q 'service=ie-config' "$log"
  grep -q 'com.docker.compose.project=insightengine' "$log"
  grep -q 'reset-admin' "$log"
  grep -q -- '--email admin@example.com' "$log"
  [ "$(cat "$tmp/state/stdin")" = "$secret" ]
  if grep -F -q "$secret" "$tmp/out" || grep -F -q "$secret" "$tmp/err" || grep -F -q "$secret" "$log"; then
    echo 'password leaked into output or the docker command log' >&2
    exit 1
  fi
  if [ "$(id -u)" -ne 0 ]; then
    set +e
    env -u RESET_SKIP_ROOT bash "$0" </dev/null >"$tmp/root.out" 2>"$tmp/root.err"
    rc=$?
    set -e
    [ "$rc" -ne 0 ]
    grep -q 'run as root' "$tmp/root.err"
  fi
  rm -rf "$tmp"
  echo "PASS  reset-admin-password forwards stdin to ie-config and does not record the password"
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    echo "NOTE  a Docker daemon is available; this self-test still used a mock and did not change a live database"
  else
    echo "SKIP  live ie-config: docker daemon is not available, so no container password was changed"
  fi
  exit 0
fi

if [ "$(id -u)" -ne 0 ] && [ "${RESET_SKIP_ROOT:-}" != 1 ]; then
  die "this reset must be run as root (sudo ./scripts/reset-admin-password.sh)"
fi

run_reset
