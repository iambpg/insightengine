#!/usr/bin/env bash
# Reset an ie-config password, or create the first Administrator if the
# users table is empty. Root only.
#
#   sudo ./scripts/reset-admin-password.sh
#   sudo ./scripts/reset-admin-password.sh --email admin@example.com
#   sudo ./scripts/reset-admin-password.sh --self-test
#
# The password is read with read -s (or stdin) and is never printed.
# An empty users table prompts for an email and creates an Administrator.
# The container is compose service ie-config (name ie-config, not CLIENT_SLUG).
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
  password="${password%$'\r'}"
  printf '%s' "$password"
}

prompt_email() {
  if [ -n "$EMAIL" ]; then
    return 0
  fi
  if [ -t 0 ]; then
    printf 'Administrator email: ' >&2
    IFS= read -r EMAIL || true
  else
    IFS= read -r EMAIL || true
  fi
  EMAIL="${EMAIL%$'\r'}"
  [ -n "$EMAIL" ] || die "an email is required when the users table is empty"
}

invoke_ie_config() {
  # $1 is reset or create. The password is read here and passed only on stdin.
  local mode=$1 password
  local -a args
  password="$(read_password)"
  args=(python -m ie_config reset-admin)
  if [ "$mode" = create ]; then
    args+=(--create --email "$EMAIL")
  elif [ -n "$EMAIL" ]; then
    args+=(--email "$EMAIL")
  fi
  if ! printf '%s' "$password" | docker exec -i "$cid" "${args[@]}"; then
    unset password
    exit 1
  fi
  unset password
}

run_reset() {
  local project cid status_out status_line errf
  if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
    die "Docker is not running, so ie-config cannot be reset from here"
  fi
  project="$(resolve_compose_project "" "$ROOT/.env" "$ROOT" "$ROOT/docker-compose.yml")"
  cid="$(find_ie_config "$project")"
  if [ -z "$cid" ]; then
    die "no ie-config container in compose project ${project}"
  fi
  errf="$(mktemp)"
  if ! status_out="$(docker exec "$cid" python -m ie_config reset-admin --status 2>"$errf")"; then
    detail="$(tr '\n' ' ' < "$errf" || true)"
    rm -f "$errf"
    die "could not read whether ie-config has users (${detail})"
  fi
  rm -f "$errf"
  status_line="$(printf '%s\n' "$status_out" | awk 'NF { print; exit }')"
  case "$status_line" in
    empty)
      say "ie-config has no users. Creating the first Administrator." >&2
      prompt_email
      invoke_ie_config create
      ;;
    admin\ *)
      invoke_ie_config reset
      ;;
    users)
      [ -n "$EMAIL" ] || die "ie-config has users but no Administrator; pass --email"
      invoke_ie_config reset
      ;;
    *)
      die "unexpected ie-config account status"
      ;;
  esac
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
    case "$*" in
      *--status*)
        printf '%s\n' "${MOCK_STATUS:-admin admin@example.com}"
        ;;
      *"$MOCK_SECRET"*)
        echo 'password appeared in docker arguments' >&2
        exit 3
        ;;
      *--create*)
        cat > "$MOCK_DIR/stdin"
        printf '%s\n' 'administrator created'
        ;;
      *)
        cat > "$MOCK_DIR/stdin"
        printf '%s\n' 'password reset for admin@example.com'
        ;;
    esac
    ;;
  *) exit 0 ;;
esac
EOF
  chmod +x "$bin/docker"
  : > "$log"
  run_case() {
    local status=$1
    shift
    : > "$log"
    : > "$tmp/state/stdin"
    # shellcheck disable=SC2031
    env -u COMPOSE_PROJECT_NAME \
      RESET_SKIP_ROOT=1 \
      "PATH=${bin}:${PATH}" \
      MOCK_LOG="$log" \
      MOCK_DIR="$tmp/state" \
      MOCK_SECRET="$secret" \
      MOCK_STATUS="$status" \
      bash "$0" "$@" >"$tmp/out" 2>"$tmp/err"
  }
  run_case "admin admin@example.com" --email admin@example.com <<<"$secret"
  grep -q 'password reset for admin@example.com' "$tmp/out"
  grep -q 'service=ie-config' "$log"
  grep -q 'com.docker.compose.project=insightengine' "$log"
  grep -q 'reset-admin' "$log"
  grep -q -- '--email admin@example.com' "$log"
  if grep -q -- '--create' "$log"; then
    echo 'reset path used --create' >&2
    exit 1
  fi
  [ "$(cat "$tmp/state/stdin")" = "$secret" ]
  if grep -F -q "$secret" "$tmp/out" || grep -F -q "$secret" "$tmp/err" || grep -F -q "$secret" "$log"; then
    echo 'password leaked into output or the docker command log' >&2
    exit 1
  fi
  run_case empty --email newadmin@example.com <<<"$secret"
  grep -q 'administrator created' "$tmp/out"
  grep -q -- '--create' "$log"
  grep -q -- '--email newadmin@example.com' "$log"
  [ "$(cat "$tmp/state/stdin")" = "$secret" ]
  if grep -F -q "$secret" "$tmp/out" || grep -F -q "$secret" "$tmp/err" || grep -F -q "$secret" "$log"; then
    echo 'password leaked while creating the administrator' >&2
    exit 1
  fi
  if grep -q '/setup/' "$tmp/out" || grep -q '/setup/' "$tmp/err"; then
    echo 'empty users table pointed at /setup/' >&2
    exit 1
  fi
  printf '%s\n%s\n' 'piped@example.com' "$secret" | run_case empty
  grep -q 'administrator created' "$tmp/out"
  grep -q -- '--create' "$log"
  grep -q -- '--email piped@example.com' "$log"
  [ "$(cat "$tmp/state/stdin")" = "$secret" ]
  if grep -F -q "$secret" "$tmp/out" || grep -F -q "$secret" "$tmp/err" || grep -F -q "$secret" "$log"; then
    echo 'password leaked while reading the email from stdin' >&2
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
  echo "PASS  an empty users table creates an Administrator and does not point at /setup/"
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
