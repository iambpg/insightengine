#!/usr/bin/env bash
# =============================================================================
# InsightEngine installer. NON-INTERACTIVE: it asks NO questions.
#
#   ./install.sh [--public-host HOST] [--alt-ports | --default-ports] [--no-start]
#   ./install.sh --fix-perms     only (re)apply owner/mode on ./secrets
#   ./install.sh --help
#
# Environment alternative to the flag: INSTALL_PUBLIC_HOST=host-or-ip
# If neither is given the host name / first IP of this machine is used (it ends up in the
# TLS certificate and in .env as PUBLIC_HOST - pass --public-host if that is wrong).
#
# What it does
#   1. checks prerequisites (openssl, awk, sed, docker + compose plugin)
#   2. creates .env (mode 600) with openssl-generated secrets - never printed -
#      with CLIENT_NAME=unconfigured / CLIENT_SLUG=unconfigured
#   3. creates a private CA + server certificate, secret files, data folders
#   4. builds/pulls images and starts the stack (docker compose up -d), including the
#      "setup" service
#
# WHICH CLIENT this server is for, and NEW INSTALL vs MOVE FROM THE OLD STACK, are NOT
# asked here: open the first-run page  https://<PUBLIC_HOST>/setup/  (README, "First run").
# This script never touches an old stack.
# =============================================================================
set -euo pipefail
umask 077
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

say()  { printf '%s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

usage() { sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

# ---- helpers ----------------------------------------------------------------
gen() {  # gen <length>  -> random alphanumeric (hex) string, no special chars
  local n=$1
  openssl rand -hex $(( n / 2 + 1 )) | cut -c1-"$n"
}
# setenv KEY VALUE : replace KEY=... in .env (value from the environment, so no
# shell/sed escaping issues). QUOTE=single wraps the value in single quotes.
setenv() {
  local key=$1 val=$2 tmp
  tmp="$(mktemp .env.XXXXXX)"
  KEY="$key" VAL="$val" awk '
    BEGIN { k = ENVIRON["KEY"]; v = ENVIRON["VAL"]; done = 0 }
    index($0, k "=") == 1 { print k "=\x27" v "\x27"; done = 1; next }
    { print }
    END { if (!done) print k "=\x27" v "\x27" }' .env > "$tmp"
  mv "$tmp" .env
  chmod 600 .env
}
getenv_val() {  # read a value back from .env (unquoted)
  local line
  line="$(grep -E "^$1=" .env | head -n1 || true)"; line="${line#*=}"; line="${line#\'}"; line="${line%\'}"; printf '%s' "$line"
}

# secret files must have NO trailing newline
write_secret() {  # write_secret <relpath> <value> <uid>
  local f="secrets/$1" v=$2 uid=${3:-0}
  mkdir -p "$(dirname "$f")"
  printf '%s' "$v" > "$f"
  apply_perm "$f" "$uid"
}
apply_perm() {  # apply_perm <file> <uid> : 0400 owned by the container uid when possible
  local f=$1 uid=$2
  if [ "$(id -u)" -eq 0 ]; then chown "$uid:$uid" "$f"; chmod 400 "$f"
  elif [ "$uid" = "$(id -u)" ] || [ "$uid" = 0 ]; then chmod 600 "$f"
  else chmod 644 "$f"; PERM_WARN=1; fi
}
PERM_WARN=0

fix_perms() {
  PERM_WARN=0
  local f uid
  [ -d secrets ] || die "no ./secrets directory yet - run ./install.sh first"
  while IFS= read -r f; do
    case "$f" in
      secrets/prometheus/*) uid=65534 ;;
      secrets/telegraf/*)   uid=10001 ;;
      secrets/trapd/*)      uid=10002 ;;
      *)                    uid=0 ;;
    esac
    apply_perm "$f" "$uid"
  done < <(find secrets -type f)
  [ "$PERM_WARN" = 1 ] && warn "not root: some secret files are mode 0644 so containers can read them. Run 'sudo ./install.sh --fix-perms' to make them 0400 owned by the container user."
  say "permissions applied"
}

PUBLIC_HOST="${INSTALL_PUBLIC_HOST:-}"
PORTS="${INSTALL_PORTS:-auto}"      # auto | alt | default
START=1
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --fix-perms) fix_perms; exit 0 ;;
    --public-host) [ $# -ge 2 ] || die "--public-host needs a value"; PUBLIC_HOST="$2"; shift 2 ;;
    --public-host=*) PUBLIC_HOST="${1#*=}"; shift ;;
    --alt-ports) PORTS=alt; shift ;;
    --default-ports) PORTS=default; shift ;;
    --no-start) START=0; shift ;;
    *) usage >&2; exit 2 ;;
  esac
done
case "$PORTS" in auto|alt|default) ;; *) die "INSTALL_PORTS must be auto, alt or default" ;; esac

# ---- prerequisites ----------------------------------------------------------
for t in openssl awk sed tr cut mktemp; do command -v "$t" >/dev/null || die "$t is required"; done
HAVE_DOCKER=0
if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then HAVE_DOCKER=1
else
  [ "$START" = 1 ] && die "docker with the compose plugin is required to start the stack (use --no-start to only prepare the files)"
  warn "docker compose not found - preparing files only."
fi

[ ! -e .env ] || die ".env already exists - not overwriting it (it holds this server's secrets). Move it away first, or edit it by hand."
[ -f .env.example ] || die ".env.example is missing"

# ---- host address (no questions: flag/env, else detect) ---------------------
if [ -z "$PUBLIC_HOST" ]; then
  PUBLIC_HOST="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
  [ -n "$PUBLIC_HOST" ] || PUBLIC_HOST="$(hostname -f 2>/dev/null || hostname 2>/dev/null || true)"
  [ -n "$PUBLIC_HOST" ] || die "could not detect this host's address - pass --public-host"
  say "PUBLIC_HOST not given; using detected value '$PUBLIC_HOST' (override with --public-host)"
fi
printf '%s' "$PUBLIC_HOST" | grep -Eq '^[A-Za-z0-9.:-]+$' || die "host must contain only letters, digits, dots, colons or dashes"

# ---- ports: use alternatives automatically when the defaults are taken ------
port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
if [ "$PORTS" = auto ]; then
  PORTS=default
  for p in 80 443 3000 9090 9093 8081 5000 8888 8444; do
    if port_busy "$p"; then PORTS=alt; say "port $p is already in use on this host -> the stack will be published on alternative ports (a running older stack is NOT touched)"; break; fi
  done
fi

say "=== InsightEngine installer (no questions asked) ==="

# ---- .env -------------------------------------------------------------------
cp .env.example .env; chmod 600 .env
# if anything below fails, do not leave a half-written .env behind (it would block a re-run)
ENV_CREATED=1
cleanup_env() { local rc=$?; if [ "$rc" -ne 0 ] && [ -n "${ENV_CREATED:-}" ]; then rm -f .env; fi; }
trap cleanup_env EXIT

setenv CLIENT_NAME "unconfigured"
setenv CLIENT_SLUG "unconfigured"
setenv INSTALL_DIR "$ROOT"
setenv PUBLIC_HOST "$PUBLIC_HOST"
setenv NETBOX_SUPERUSER_EMAIL "admin@${PUBLIC_HOST}"

setenv GRAFANA_ADMIN_PASSWORD "$(gen 24)"
setenv GRAFANA_SECRET_KEY "$(gen 48)"
setenv NETBOX_DB_PASSWORD "$(gen 32)"
setenv NETBOX_REDIS_PASSWORD "$(gen 32)"
setenv NETBOX_REDIS_CACHE_PASSWORD "$(gen 32)"
setenv NETBOX_SECRET_KEY "$(gen 64)"
setenv NETBOX_API_TOKEN_PEPPER_1 "$(gen 64)"
setenv NETBOX_SUPERUSER_PASSWORD "$(gen 24)"
setenv NETBOX_SUPERUSER_API_TOKEN "$(gen 40)"
setenv AP_ENCRYPTION_KEY "$(gen 32)"
setenv AP_JWT_SECRET "$(gen 48)"
setenv AP_POSTGRES_PASSWORD "$(gen 32)"
setenv AP_REDIS_PASSWORD "$(gen 32)"
setenv NETDISCO_DB_PASSWORD "$(gen 32)"
setenv IE_DB_PASSWORD "$(gen 32)"
setenv IE_CONFIG_DB_PASSWORD "$(gen 32)"
setenv SNMP_V3_USERNAME "$(getenv_val SNMP_V3_USER)"

if [ -S /var/run/docker.sock ]; then
  gid="$(stat -c %g /var/run/docker.sock 2>/dev/null || true)"
  [ -n "$gid" ] && setenv DOCKER_GID "$gid"
fi

if [ "$PORTS" = alt ]; then
  setenv PORT_HTTP 8080;        setenv PORT_HTTPS 8443
  setenv PORT_GRAFANA 13000;    setenv PORT_PROMETHEUS 19090
  setenv PORT_ALERTMANAGER 19093; setenv PORT_ACTIVEPIECES 18081
  setenv PORT_NETDISCO 15000;   setenv PORT_OXIDIZED 18888
  setenv PORT_NETBOX 18444
  setenv PORT_SYSLOG 5514;      setenv PORT_TRAPS 1162
fi

# basic-auth hash for Prometheus/Alertmanager/Oxidized in front of Caddy
ADMIN_PW="$(gen 24)"
hash=""
if command -v htpasswd >/dev/null; then
  hash="$(printf '%s\n' "$ADMIN_PW" | htpasswd -niB x 2>/dev/null | cut -d: -f2- | tr -d '\n' || true)"
fi
if [ -z "$hash" ] && command -v python3 >/dev/null && python3 -c 'import bcrypt' 2>/dev/null; then
  hash="$(ADMIN_PW="$ADMIN_PW" python3 -c 'import bcrypt,os;print(bcrypt.hashpw(os.environ["ADMIN_PW"].encode(),bcrypt.gensalt(12)).decode(),end="")' || true)"
fi
if [ -z "$hash" ] && [ "$HAVE_DOCKER" = 1 ]; then
  img="$(getenv_val CADDY_IMAGE)"
  hash="$(printf '%s\n' "$ADMIN_PW" | docker run --rm -i "$img" caddy hash-password 2>/dev/null | tr -d '\r\n' || true)"
fi
hash="${hash/\$2y\$/\$2a\$}"
case "$hash" in
  \$2a\$*|\$2b\$*) setenv ADMIN_BASIC_HASH "$hash"; setenv ADMIN_BASIC_PASSWORD "$ADMIN_PW" ;;
  *) die "could not create a bcrypt hash for the admin basic-auth (need htpasswd, python3-bcrypt or docker). Install one and re-run (remove the partly written .env first)." ;;
esac
unset ADMIN_PW hash

# ---- certificates --------------------------------------------------------
mkdir -p certs
if [ ! -f certs/ca.crt ]; then
  say "creating a private CA and server certificate in ./certs"
  san="DNS:caddy,DNS:localhost"
  if printf '%s' "$PUBLIC_HOST" | grep -Eq '^[0-9.]+$|^[0-9A-Fa-f:]+:[0-9A-Fa-f:]*$'; then san="$san,IP:$PUBLIC_HOST"; else san="$san,DNS:$PUBLIC_HOST"; fi
  openssl genrsa -out certs/ca.key 4096 2>/dev/null
  openssl req -x509 -new -nodes -key certs/ca.key -sha256 -days 3650 \
    -subj "/O=InsightEngine/CN=InsightEngine CA ($(date +%Y))" -out certs/ca.crt
  openssl genrsa -out certs/server.key 2048 2>/dev/null
  openssl req -new -key certs/server.key -subj "/O=InsightEngine/CN=${PUBLIC_HOST}" -out certs/server.csr
  printf 'subjectAltName=%s\nextendedKeyUsage=serverAuth\nbasicConstraints=CA:FALSE\n' "$san" > certs/server.ext
  openssl x509 -req -in certs/server.csr -CA certs/ca.crt -CAkey certs/ca.key -CAcreateserial \
    -out certs/server.crt -days 825 -sha256 -extfile certs/server.ext 2>/dev/null
  rm -f certs/server.csr certs/server.ext certs/ca.srl
  chmod 600 certs/*.key; chmod 644 certs/ca.crt certs/server.crt
  say "  (import certs/ca.crt into browsers/clients that should trust this server)"
fi

# ---- secret files, folders ------------------------------------------------
mkdir -p secrets data/netdisco/logs data/migration data/setup migration cust-exporter/app config/netdisco/nd-site-local
# The Prometheus and Oxidized token files start as the NetBox superuser token so a device
# added after first-run is monitored with no extra step. This token is privileged.
# Replace it with a read-only token: scripts/set-secret.sh prometheus/netbox.token
NB_TOKEN="$(getenv_val NETBOX_SUPERUSER_API_TOKEN)"
write_secret prometheus/netbox.token "$NB_TOKEN" 65534
write_secret oxidized/netbox.token "$NB_TOKEN" 0
unset NB_TOKEN
write_secret oxidized/device_username "" 0
write_secret oxidized/device_password "" 0
write_secret trapd/trap_community "" 10002
write_secret trapd/v3_users.conf "" 10002
for s in fortigate_token panos_api_key ise_credentials dnac_credentials sdwan_credentials; do
  write_secret "telegraf/$s" "" 10001
done
write_secret cust-exporter/netbox.token "unset-placeholder" 0
# token for the setup service API (the operator pastes it into the first-run page)
write_secret setup/token "$(gen 48)" 0
[ "$PERM_WARN" = 1 ] && warn "not root: secret files for container users are mode 0644. Run 'sudo ./install.sh --fix-perms' to tighten them."


# from here on a failure must not delete .env
ENV_CREATED=

# Build local images. IE_UI_IMAGE, when set to something other than insightengine-ui:local,
# is pulled and not built. ui/Dockerfile is the Next.js UI (npm ci, NEXT_PUBLIC_IE_API_MODE=live,
# port 8080, GET /healthz). If that file is missing, the placeholder Dockerfile is used
# so the stack still starts (it serves ui/placeholder/).
prepare_ui() {
  local ui
  ui="$(getenv_val IE_UI_IMAGE)"
  if [ -n "$ui" ] && [ "$ui" != "insightengine-ui:local" ]; then
    say "IE_UI_IMAGE is set; the UI image will be pulled and ui/ will not be built"
    export IE_UI_SKIP_BUILD=1
    return
  fi
  if [ ! -f ui/Dockerfile ]; then
    say "ui/Dockerfile is not present; building the placeholder UI (Dockerfile.placeholder)"
    export IE_UI_DOCKERFILE=Dockerfile.placeholder
  fi
}

# ---- start the stack ---------------------------------------------------------
if [ "$START" = 1 ]; then
  say "building local images and pulling the others (this can take several minutes)..."
  prepare_ui
  nbimg="$(getenv_val NETBOX_IMAGE)"
  skip=""
  if [ "${IE_UI_SKIP_BUILD:-0}" = 1 ]; then skip="$skip insightengine-ui"; fi
  if [ -n "$nbimg" ] && [ "$nbimg" != "insightengine/netbox-lists:local" ]; then
    say "NETBOX_IMAGE is set; pulling that image and not building the local plugin image"
    skip="$skip netbox"
  fi
  # Only services that declare a build section. Names come from compose config, not from the user.
  build_list="$(IE_BUILD_SKIP="$skip" python3 - <<'PY'
import json, os, subprocess
skip = set(os.environ.get("IE_BUILD_SKIP", "").split())
raw = subprocess.check_output(["docker", "compose", "config", "--format", "json"])
cfg = json.loads(raw)
for name, svc in cfg.get("services", {}).items():
    if name in skip or not svc.get("build"):
        continue
    print(name)
PY
)"
  # shellcheck disable=SC2086
  [ -n "$build_list" ] && docker compose build $build_list
  if [ "${IE_UI_SKIP_BUILD:-0}" = 1 ]; then docker compose pull insightengine-ui; fi
  if [ -n "$nbimg" ] && [ "$nbimg" != "insightengine/netbox-lists:local" ]; then docker compose pull netbox; fi
  docker compose pull --ignore-buildable
  say "starting the stack..."
  docker compose up -d --no-build
else
  say "--no-start given: nothing started. Later: ./install.sh   (or docker compose build && docker compose up -d)"
fi

# ---- summary (no secrets printed) --------------------------------------------
HTTPS_PORT="$(getenv_val PORT_HTTPS)"; HTTPS_PORT="${HTTPS_PORT:-443}"
url="https://${PUBLIC_HOST}"; [ "$HTTPS_PORT" = 443 ] || url="$url:$HTTPS_PORT"
say ""
say "=== done ==="
say "Configuration : .env (mode 600) holds the generated passwords. This script does not print them."
say "Certificates  : certs/ca.crt (private CA - import it into browsers that should trust this server)"
say "FIRST RUN     : open  ${url}/setup/  and paste the setup token."
say "                The token is in the file  secrets/setup/token  (read it yourself, e.g. 'sudo cat secrets/setup/token')."
say "                Then: client name, the first administrator email and password, then new install or move."
say "                The administrator password is chosen on that page. This script does not print it."
say "ONE CLONE     : this repository is the whole product (stack + UI under ui/). A second clone is not required."
say "Other        : API tokens (NetBox etc.): scripts/set-secret.sh <name> ; optional features: COMPOSE_PROFILES in .env"
