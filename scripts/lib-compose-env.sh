#!/usr/bin/env bash
# Shared by scripts/upgrade.sh and scripts/migrate-pg-volumes.sh.
# shellcheck shell=bash
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  echo "source this file; do not execute it" >&2
  exit 2
fi

env_file_value() {
  local key=$1 file=${2:-.env} line
  [ -f "$file" ] || return 0
  line="$(grep -E "^${key}=" "$file" | tail -n1 || true)"
  line="${line#*=}"
  line="${line#\'}"
  line="${line%\'}"
  line="${line#\"}"
  line="${line%\"}"
  printf '%s' "$line"
}

# Secrets install.sh --no-start will generate when they are missing or empty.
backfill_secret_keys() {
  cat <<'EOF'
NETBOX_SUPERUSER_API_KEY
NETBOX_SUPERUSER_API_TOKEN
NETBOX_SUPERUSER_PASSWORD
NETBOX_DB_PASSWORD
NETBOX_REDIS_PASSWORD
NETBOX_REDIS_CACHE_PASSWORD
NETBOX_SECRET_KEY
NETBOX_API_TOKEN_PEPPER_1
GRAFANA_ADMIN_PASSWORD
GRAFANA_SECRET_KEY
AP_ENCRYPTION_KEY
AP_JWT_SECRET
AP_POSTGRES_PASSWORD
AP_REDIS_PASSWORD
NETDISCO_DB_PASSWORD
IE_DB_PASSWORD
IE_CONFIG_DB_PASSWORD
EOF
}

# Every compose ${VAR:?run install.sh}. Placeholders are exported only in a
# subshell so `docker compose config` can run before those keys exist.
compose_required_keys() {
  cat <<'EOF'
NETBOX_DB_PASSWORD
NETBOX_REDIS_PASSWORD
NETBOX_REDIS_CACHE_PASSWORD
NETBOX_SECRET_KEY
NETBOX_API_TOKEN_PEPPER_1
NETBOX_SUPERUSER_PASSWORD
NETBOX_SUPERUSER_API_KEY
NETBOX_SUPERUSER_API_TOKEN
AP_ENCRYPTION_KEY
AP_JWT_SECRET
AP_POSTGRES_PASSWORD
AP_REDIS_PASSWORD
PUBLIC_HOST
ADMIN_BASIC_HASH
INSTALL_DIR
IE_CONFIG_DB_PASSWORD
NETDISCO_DB_PASSWORD
GRAFANA_ADMIN_PASSWORD
GRAFANA_SECRET_KEY
IE_DB_PASSWORD
EOF
}

compose_export_placeholders() {
  local file=$1 key val
  [ -n "$file" ] || file=".env"
  while IFS= read -r key; do
    [ -n "$key" ] || continue
    if [ -n "${!key:-}" ]; then
      continue
    fi
    val="$(env_file_value "$key" "$file")"
    if [ -n "$val" ]; then
      continue
    fi
    export "${key}=placeholder-not-a-secret"
  done < <(compose_required_keys)
}

compose_config_project_name() {
  local envfile=$1 root=$2 json
  json="$(
    (
      compose_export_placeholders "$envfile"
      docker compose --project-directory "$root" config --format json
    ) 2>/dev/null
  )" || return 1
  [ -n "$json" ] || return 1
  printf '%s' "$json" | python3 -c 'import json,sys
try:
    data=json.load(sys.stdin)
except Exception:
    raise SystemExit(1)
name=str(data.get("name") or "").strip()
if not name:
    raise SystemExit(1)
sys.stdout.write(name)
'
}

compose_file_project_name() {
  local file=$1 line
  [ -n "$file" ] && [ -f "$file" ] || return 1
  line="$(grep -E '^name:[[:space:]]*[A-Za-z0-9][A-Za-z0-9_-]*[[:space:]]*$' "$file" | head -n1 || true)"
  [ -n "$line" ] || return 1
  line="${line#name:}"
  line="${line#"${line%%[![:space:]]*}"}"
  line="${line%"${line##*[![:space:]]}"}"
  [ -n "$line" ] || return 1
  printf '%s' "$line"
}

project_from_container_labels() {
  local name service
  for service in netbox-postgres insightengine-postgres; do
    name="$(
      docker ps -a \
        --filter "label=com.docker.compose.service=${service}" \
        --format '{{.Label "com.docker.compose.project"}}' 2>/dev/null \
        | awk 'NF { print; exit }' || true
    )"
    if [ -n "$name" ]; then
      printf '%s' "$name"
      return 0
    fi
  done
  return 1
}

# 1 explicit (--project)
# 2 COMPOSE_PROJECT_NAME in the environment
# 3 COMPOSE_PROJECT_NAME in the env file
# 4 docker compose config --format json  (.name), with placeholders
# 5 literal top-level name: in the compose file
# 6 com.docker.compose.project on a postgres container
# 7 directory name
resolve_compose_project() {
  local explicit=${1:-} envfile=${2:-.env} root=${3:-.} composefile=${4:-} name
  if [ -z "$composefile" ]; then
    composefile="${root}/docker-compose.yml"
  fi
  if [ -n "$explicit" ]; then
    printf '%s' "$explicit"
    return 0
  fi
  if [ -n "${COMPOSE_PROJECT_NAME:-}" ]; then
    printf '%s' "${COMPOSE_PROJECT_NAME}"
    return 0
  fi
  name="$(env_file_value COMPOSE_PROJECT_NAME "$envfile")"
  if [ -n "$name" ]; then
    printf '%s' "$name"
    return 0
  fi
  if name="$(compose_config_project_name "$envfile" "$root")"; then
    if [ -n "$name" ]; then
      printf '%s' "$name"
      return 0
    fi
  fi
  if name="$(compose_file_project_name "$composefile")"; then
    if [ -n "$name" ]; then
      printf '%s' "$name"
      return 0
    fi
  fi
  if name="$(project_from_container_labels)"; then
    if [ -n "$name" ]; then
      printf '%s' "$name"
      return 0
    fi
  fi
  name="$(basename "$root" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-')"
  if [ -z "$name" ]; then
    name="insightengine"
  fi
  printf '%s' "$name"
}

compose_env_self_test() {
  (
    set -euo pipefail
    local tmp bin repo r3 envfile got fake
    tmp="$(mktemp -d)"
    bin="$tmp/bin"
    mkdir -p "$bin" "$tmp/r3"
    r3="$tmp/r3"
    repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    fake="$bin/docker"
    cat > "$fake" <<'EOF'
#!/bin/bash
if [ "$1" = "compose" ]; then
  if [ "${MOCK_CONFIG_FAIL:-0}" = 1 ]; then
    echo "config failed" >&2
    exit 1
  fi
  printf '%s\n' '{"name":"insightengine"}'
  exit 0
fi
if [ "$1" = "ps" ]; then
  if [ -n "${MOCK_LABEL_PROJECT:-}" ]; then
    printf '%s\n' "$MOCK_LABEL_PROJECT"
  fi
  exit 0
fi
echo "unexpected docker $*" >&2
exit 1
EOF
    chmod +x "$fake"
    export PATH="$bin:$PATH"

    got="$(compose_file_project_name "$repo/docker-compose.yml")"
    [ "$got" = "insightengine" ]

    envfile="$tmp/empty.env"
    printf '%s\n' "PUBLIC_HOST=example" > "$envfile"
    printf '%s\n' "name: other" > "$tmp/other.yml"
    : > "$tmp/noname.yml"

    got="$(resolve_compose_project "" "$envfile" "$r3" "$tmp/other.yml")"
    [ "$got" = "insightengine" ]

    got="$(MOCK_CONFIG_FAIL=1 resolve_compose_project "" "$envfile" "$r3" "$repo/docker-compose.yml")"
    [ "$got" = "insightengine" ]

    got="$(MOCK_CONFIG_FAIL=1 MOCK_LABEL_PROJECT=from-label resolve_compose_project "" "$envfile" "$r3" "$tmp/noname.yml")"
    [ "$got" = "from-label" ]

    got="$(MOCK_CONFIG_FAIL=1 resolve_compose_project "" "$envfile" "$r3" "$tmp/noname.yml")"
    [ "$got" = "r3" ]

    printf '%s\n' "COMPOSE_PROJECT_NAME=from-dotenv" > "$tmp/dotenv.env"
    got="$(resolve_compose_project "" "$tmp/dotenv.env" "$r3" "$tmp/other.yml")"
    [ "$got" = "from-dotenv" ]

    got="$(COMPOSE_PROJECT_NAME=from-shell resolve_compose_project "" "$tmp/dotenv.env" "$r3" "$tmp/other.yml")"
    [ "$got" = "from-shell" ]

    got="$(resolve_compose_project "explicit-name" "$tmp/dotenv.env" "$r3" "$tmp/other.yml")"
    [ "$got" = "explicit-name" ]

    quoted="$tmp/quoted.env"
    printf "%s\n" "COMPOSE_PROJECT_NAME='from-dotenv'" > "$quoted"
    got="$(env_file_value COMPOSE_PROJECT_NAME "$quoted")"
    [ "$got" = "from-dotenv" ]

    rm -rf "$tmp"
    echo "PASS  compose project is config, then file name, then container label, then directory"
  )
}
