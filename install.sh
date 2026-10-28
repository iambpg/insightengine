#!/usr/bin/env bash
# =============================================================================
# InsightEngine installer. NON-INTERACTIVE: it asks NO questions.
#
#   ./install.sh [--public-host HOST] [--alt-ports | --default-ports] [--no-start]
#   ./install.sh --upgrade-env [--no-start] [--dry-run]
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
#   3. probes every published host port (ss, lsof, Docker, and iptables NAT)
#      and writes free PORT_* values into .env. A Kubernetes loadbalancer
#      DNAT (k3s Traefik on the node IP) is invisible to ss.
#   4. creates a private CA + server certificate, secret files, data folders
#   5. builds/pulls images and starts the stack (docker compose up -d), including the
#      "setup" service
#
# Re-run: if .env exists and .install-started contains exactly past-secret-generation,
# the script resumes at certificates, image build, and start. It does not regenerate
# or print secrets that are already set. A missing or empty required key (an older
# .env has no NETBOX_SUPERUSER_API_KEY) is filled in. Ports and other values stay.
# Use --no-start when you still need to copy Postgres data before the stack starts.
# --public-host and the port flags apply only when .env is first created.
# A plain ./install.sh stops when .env exists without that marker and leaves the
# file untouched. --upgrade-env (same as --backfill-env) is the upgrade path for
# an install written before the marker existed. It accepts that .env only when
# PUBLIC_HOST, CLIENT_NAME, CLIENT_SLUG, INSTALL_DIR, NETBOX_DB_PASSWORD, and
# NETBOX_SECRET_KEY are present and non-empty, fills only missing or empty
# secrets, writes the marker after that backfill, and does not change the host,
# client, ports, or certificates that already exist. --dry-run with --upgrade-env
# prints the plan and writes nothing. A partial or corrupt .env is refused.
#
# WHICH CLIENT this server is for, and NEW INSTALL vs MOVE FROM THE OLD STACK, are NOT
# asked here: open the first-run page  https://<PUBLIC_HOST>[:PORT_HTTPS]/setup/
# (README, "First run"). This script never touches an old stack.
# =============================================================================
set -euo pipefail
umask 077
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

say()  { printf '%s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  awk 'NR < 2 { next } /^set -euo pipefail$/ { exit } { sub(/^# ?/, ""); print }' "${BASH_SOURCE[0]}"
}

# ---- helpers ----------------------------------------------------------------
gen() {  # gen <length>  -> random alphanumeric (hex) string, no special chars
  local n=$1
  openssl rand -hex $(( n / 2 + 1 )) | cut -c1-"$n"
}
# .env stays mode 600. Under sudo, give it back to the invoking user so a later
# non-root `docker compose` can read it. Secret files keep their container owners.
own_private_env() {
  local f=$1 gid
  [ -f "$f" ] || return 0
  chmod 600 "$f" || true
  if [ "$(id -u)" -eq 0 ] && [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
    gid="$(id -g "$SUDO_USER" 2>/dev/null || true)"
    if [ -n "$gid" ]; then
      chown "$SUDO_USER:$gid" "$f" || true
    fi
  fi
}
# Collapse repeated KEY= lines (keep the last). Comments and blank lines stay.
dedupe_env() {
  local file=${1:-.env} tmp
  [ -f "$file" ] || return 0
  tmp="$(mktemp "${file}.XXXXXX")"
  awk '
    /^[A-Za-z_][A-Za-z0-9_]*=/ {
      key = $0
      sub(/=.*/, "", key)
      last[key] = NR
      text[NR] = $0
      keys[NR] = key
      assign[NR] = 1
      next
    }
    { text[NR] = $0; assign[NR] = 0 }
    END {
      for (i = 1; i <= NR; i++) {
        if (assign[i] && last[keys[i]] != i) continue
        print text[i]
      }
    }
  ' "$file" > "$tmp"
  mv "$tmp" "$file"
  own_private_env "$file"
}
# setenv KEY VALUE : replace KEY=... in .env (value from the environment, so no
# shell/sed escaping issues). The value is wrapped in single quotes.
# Every exact KEY= line is replaced once; a missing key is appended once.
setenv() {
  local key=$1 val=$2 tmp file
  file="${ENV_FILE:-.env}"
  tmp="$(mktemp "${file}.XXXXXX")"
  KEY="$key" VAL="$val" awk '
    BEGIN { k = ENVIRON["KEY"]; v = ENVIRON["VAL"]; done = 0 }
    {
      line = $0
      sub(/\r$/, "", line)
      if (index(line, k "=") == 1) {
        if (!done) print k "=\x27" v "\x27"
        done = 1
        next
      }
      print line
    }
    END { if (!done) print k "=\x27" v "\x27" }
  ' "$file" > "$tmp"
  mv "$tmp" "$file"
  own_private_env "$file"
}
getenv_val() {  # read a value back from .env (unquoted). Last assignment wins.
  local line file
  file="${ENV_FILE:-.env}"
  line="$(grep -E "^$1=" "$file" | tail -n1 || true)"; line="${line#*=}"; line="${line#\'}"; line="${line%\'}"; printf '%s' "$line"
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

# Every host port docker-compose.yml publishes. Caddy's container ports match
# these values. Syslog and traps keep container ports 6514 and 1162.
# proto is tcp, udp, or both (Docker allocates each protocol separately).
TAKEN_PORTS=" "
PORT_PLAN=""
PORT_BUSY_REASON=""
IPTABLES_NAT_CACHE=""
IPTABLES_NAT_LOADED=0
load_iptables_nat() {
  # Empty when iptables is missing or not readable (non-root). Cached so the
  # probe does not take the xtables lock once per port.
  if [ "$IPTABLES_NAT_LOADED" = 1 ]; then return 0; fi
  IPTABLES_NAT_LOADED=1
  IPTABLES_NAT_CACHE=""
  local bin dump
  for bin in iptables ip6tables; do
    if command -v "$bin" >/dev/null 2>&1; then
      dump="$("$bin" -t nat -S 2>/dev/null || true)"
      IPTABLES_NAT_CACHE="${IPTABLES_NAT_CACHE}"$'\n'"${dump}"
    fi
  done
}
public_host_ip_pattern() {
  # ERE alternation of addresses for the -d match. A bare IP is itself.
  # A DNS name is resolved; failure leaves the pattern empty (no match).
  local raw="" ip first=1 out=""
  if printf '%s' "$PUBLIC_HOST" | grep -Eq '^[0-9.]+$|^[0-9A-Fa-f:]+:[0-9A-Fa-f:]*$'; then
    raw="$PUBLIC_HOST"
  elif command -v getent >/dev/null 2>&1; then
    raw="$(getent ahosts "$PUBLIC_HOST" 2>/dev/null | awk '{print $1}' | sort -u)"
  fi
  [ -n "$raw" ] || return 1
  while IFS= read -r ip; do
    [ -n "$ip" ] || continue
    ip="$(printf '%s' "$ip" | sed 's/[.]/\\./g')"
    if [ "$first" = 1 ]; then out="$ip"; first=0; else out="${out}|${ip}"; fi
  done <<EOF
$raw
EOF
  [ -n "$out" ] || return 1
  printf '%s' "$out"
}
kube_lb_claims_port() { # kube_lb_claims_port <port> -> 0 when KUBE-SERVICES DNATs PUBLIC_HOST
  # k3s Traefik (ServiceLB) installs, for example:
  #   -A KUBE-SERVICES -d <node-ip>/32 ... --comment "... loadbalancer IP" --dport 443 -j ...
  # ss does not show that. Docker can still publish 443 and never receive the packet.
  # A dport match on a different address, or a Docker DNAT, is not this rule.
  local port=$1 line ips
  load_iptables_nat
  [ -n "${IPTABLES_NAT_CACHE//[[:space:]]/}" ] || return 1
  ips="$(public_host_ip_pattern 2>/dev/null || true)"
  [ -n "$ips" ] || return 1
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    printf '%s\n' "$line" | grep -Eq -- "--dport ${port}([[:space:]]|$)" || continue
    printf '%s\n' "$line" | grep -q 'KUBE-SERVICES' || continue
    printf '%s\n' "$line" | grep -qi 'loadbalancer' || continue
    printf '%s\n' "$line" | grep -Eq -- "-d (${ips})/(32|128)" && return 0
  done <<EOF
$IPTABLES_NAT_CACHE
EOF
  return 1
}
host_port_busy() { # host_port_busy <port> <tcp|udp|both>
  local port=$1 proto=$2 published
  PORT_BUSY_REASON=""
  case " $TAKEN_PORTS " in
    *" $port "*) return 0 ;;
  esac
  if command -v ss >/dev/null 2>&1; then
    if [ "$proto" != udp ] && ss -H -ltn "sport = :$port" 2>/dev/null | grep -q .; then return 0; fi
    if [ "$proto" != tcp ] && ss -H -lun "sport = :$port" 2>/dev/null | grep -q .; then return 0; fi
  fi
  if command -v lsof >/dev/null 2>&1; then
    if [ "$proto" != udp ] && lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then return 0; fi
    if [ "$proto" != tcp ] && lsof -nP -iUDP:"$port" >/dev/null 2>&1; then return 0; fi
  fi
  if [ "$proto" != udp ] && (exec 3<>"/dev/tcp/127.0.0.1/$port") >/dev/null 2>&1; then return 0; fi
  if [ "${HAVE_DOCKER:-0}" = 1 ]; then
    published="$(docker ps --format '{{.Ports}}' 2>/dev/null || true)"
    # ":80->" must not match ":8080->".
    if printf '%s\n' "$published" | grep -Eq ":${port}->"; then return 0; fi
  fi
  if kube_lb_claims_port "$port"; then
    PORT_BUSY_REASON="claimed by a Kubernetes loadbalancer (iptables KUBE-SERVICES DNAT for ${PUBLIC_HOST}; ss does not show this)"
    return 0
  fi
  return 1
}
say_port_move() { # say_port_move <label> <from> <to> <reason>
  local label=$1 from=$2 to=$3 reason=$4
  if [ -n "$reason" ]; then
    say "$label: port $from is $reason; using $to" >&2
  else
    say "$label: port $from is in use; using $to" >&2
  fi
}
choose_host_port() { # choose_host_port <label> <default> <preferred> <proto>  -> stdout
  local label=$1 default=$2 preferred=$3 proto=$4 start candidate n reason=""
  if [ "$PORTS" = default ]; then
    if host_port_busy "$default" "$proto"; then
      if [ -n "$PORT_BUSY_REASON" ]; then
        die "$label port $default is ${PORT_BUSY_REASON}. Re-run without --default-ports so a free port can be chosen."
      fi
      die "$label port $default is in use. Re-run without --default-ports so a free port can be chosen."
    fi
    printf '%s' "$default"
    return 0
  fi
  if [ "$PORTS" = alt ]; then start=$preferred; else start=$default; fi
  if ! host_port_busy "$start" "$proto"; then
    printf '%s' "$start"
    return 0
  fi
  reason=$PORT_BUSY_REASON
  if [ "$start" != "$preferred" ] && ! host_port_busy "$preferred" "$proto"; then
    say_port_move "$label" "$start" "$preferred" "$reason"
    printf '%s' "$preferred"
    return 0
  fi
  candidate=$preferred
  n=0
  while [ "$n" -lt 200 ]; do
    if ! host_port_busy "$candidate" "$proto"; then
      say_port_move "$label" "$start" "$candidate" "$reason"
      printf '%s' "$candidate"
      return 0
    fi
    candidate=$((candidate + 1))
    if [ "$candidate" -gt 65535 ]; then candidate=20000; fi
    n=$((n + 1))
  done
  die "no free host port for $label near $preferred"
}
plan_one_port() { # plan_one_port <KEY> <default> <preferred> <proto>
  local chosen
  chosen="$(choose_host_port "$1" "$2" "$3" "$4")"
  TAKEN_PORTS="$TAKEN_PORTS $chosen"
  PORT_PLAN="${PORT_PLAN}${1}=${chosen}"$'\n'
}
plan_published_ports() {
  TAKEN_PORTS=" "
  PORT_PLAN=""
  plan_one_port PORT_HTTP 80 8080 tcp
  plan_one_port PORT_HTTPS 443 8443 both
  plan_one_port PORT_GRAFANA 3000 13000 tcp
  plan_one_port PORT_PROMETHEUS 9090 19090 tcp
  plan_one_port PORT_ALERTMANAGER 9093 19093 tcp
  plan_one_port PORT_ACTIVEPIECES 8081 18081 tcp
  plan_one_port PORT_NETDISCO 5000 15000 tcp
  plan_one_port PORT_OXIDIZED 8888 18888 tcp
  plan_one_port PORT_NETBOX 8444 18444 tcp
  plan_one_port PORT_SYSLOG 514 5514 both
  plan_one_port PORT_TRAPS 162 1162 udp
}
apply_port_plan() {
  local line key val https
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    key=${line%%=*}
    val=${line#*=}
    setenv "$key" "$val"
  done <<EOF
$PORT_PLAN
EOF
  https="$(getenv_val PORT_HTTPS)"
  if [ "$https" = 443 ]; then setenv HTTPS_PORT_SUFFIX ""
  else setenv HTTPS_PORT_SUFFIX ":${https}"; fi
}
print_port_table() {
  local http https grafana prom am ap nd ox nb syslog traps origin
  http="$(getenv_val PORT_HTTP)"; http="${http:-80}"
  https="$(getenv_val PORT_HTTPS)"; https="${https:-443}"
  grafana="$(getenv_val PORT_GRAFANA)"; grafana="${grafana:-3000}"
  prom="$(getenv_val PORT_PROMETHEUS)"; prom="${prom:-9090}"
  am="$(getenv_val PORT_ALERTMANAGER)"; am="${am:-9093}"
  ap="$(getenv_val PORT_ACTIVEPIECES)"; ap="${ap:-8081}"
  nd="$(getenv_val PORT_NETDISCO)"; nd="${nd:-5000}"
  ox="$(getenv_val PORT_OXIDIZED)"; ox="${ox:-8888}"
  nb="$(getenv_val PORT_NETBOX)"; nb="${nb:-8444}"
  syslog="$(getenv_val PORT_SYSLOG)"; syslog="${syslog:-514}"
  traps="$(getenv_val PORT_TRAPS)"; traps="${traps:-162}"
  if [ "$https" = 443 ]; then origin="https://${PUBLIC_HOST}"; else origin="https://${PUBLIC_HOST}:${https}"; fi
  say "Published host ports:"
  say "  setup / UI        ${origin}/setup/    (PORT_HTTP=${http} PORT_HTTPS=${https})"
  say "  Grafana           https://${PUBLIC_HOST}:${grafana}/"
  say "  Prometheus        https://${PUBLIC_HOST}:${prom}/"
  say "  Alertmanager      https://${PUBLIC_HOST}:${am}/"
  say "  Activepieces      https://${PUBLIC_HOST}:${ap}/"
  say "  Netdisco          https://${PUBLIC_HOST}:${nd}/"
  say "  Oxidized          https://${PUBLIC_HOST}:${ox}/"
  say "  NetBox            https://${PUBLIC_HOST}:${nb}/"
  say "  syslog            ${syslog}/tcp+udp"
  say "  SNMP traps        ${traps}/udp"
}

# Tests source this file to call setenv/dedupe_env. Stop before any install work.
# scripts/test-env-once.sh sources this file. Return only in that case.
if [ "${INSTALL_SH_SOURCE_ONLY:-}" = 1 ] && [ "${BASH_SOURCE[0]}" != "$0" ]; then
  return 0
fi

PUBLIC_HOST_FROM_FLAG=0
PUBLIC_HOST="${INSTALL_PUBLIC_HOST:-}"
PORTS="${INSTALL_PORTS:-auto}"      # auto | alt | default
START=1
UPGRADE_ENV=0
DRY_RUN=0
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --fix-perms) fix_perms; exit 0 ;;
    --public-host) [ $# -ge 2 ] || die "--public-host needs a value"; PUBLIC_HOST="$2"; PUBLIC_HOST_FROM_FLAG=1; shift 2 ;;
    --public-host=*) PUBLIC_HOST="${1#*=}"; PUBLIC_HOST_FROM_FLAG=1; shift ;;
    --alt-ports) PORTS=alt; shift ;;
    --default-ports) PORTS=default; shift ;;
    --no-start) START=0; shift ;;
    --upgrade-env|--backfill-env) UPGRADE_ENV=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    *) usage >&2; exit 2 ;;
  esac
done
if [ "$DRY_RUN" = 1 ] && [ "$UPGRADE_ENV" != 1 ]; then
  die "--dry-run is only valid with --upgrade-env"
fi
case "$PORTS" in auto|alt|default) ;; *) die "INSTALL_PORTS must be auto, alt or default" ;; esac

# ---- prerequisites ----------------------------------------------------------
for t in openssl awk sed tr cut mktemp; do command -v "$t" >/dev/null || die "$t is required"; done
HAVE_DOCKER=0
if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then HAVE_DOCKER=1
else
  [ "$START" = 1 ] && die "docker with the compose plugin is required to start the stack (use --no-start to only prepare the files)"
  warn "docker compose not found - preparing files only."
fi

RESUME=0
WRITE_MARKER=0
if [ -e .env ]; then
  if [ -f .install-started ] && grep -qx 'past-secret-generation' .install-started; then
    RESUME=1
  elif [ "$UPGRADE_ENV" = 1 ]; then
    RESUME=1
    WRITE_MARKER=1
  else
    die ".env already exists - not overwriting it (it holds this server's secrets). Move it away first, or edit it by hand."
  fi
elif [ "$UPGRADE_ENV" = 1 ]; then
  die "--upgrade-env needs an existing .env; nothing was written"
fi
[ -f .env.example ] || die ".env.example is missing"

cleanup_env() {
  local rc=$?
  if [ "$rc" -ne 0 ] && [ -n "${ENV_CREATED:-}" ]; then
    rm -f .env .install-started
  fi
}
trap cleanup_env EXIT

# Fill a required secret only when the key is absent or empty. A non-empty
# value is the one the running databases already use and must not be replaced.
# dry=1 prints the key name and does not write.
backfill_empty() {
  local key=$1 len=$2 dry=${3:-0} cur
  cur="$(getenv_val "$key")"
  if [ -z "$cur" ]; then
    if [ "$dry" = 1 ]; then
      say "would add $key (missing or empty; value is not printed)"
    else
      setenv "$key" "$(gen "$len")"
      say "backfilled $key (missing or empty; existing secrets were not changed)"
    fi
  fi
}

backfill_required_secrets() {
  local dry=$1
  backfill_empty NETBOX_SUPERUSER_API_KEY 12 "$dry"
  backfill_empty NETBOX_SUPERUSER_API_TOKEN 40 "$dry"
  backfill_empty NETBOX_SUPERUSER_PASSWORD 24 "$dry"
  backfill_empty NETBOX_DB_PASSWORD 32 "$dry"
  backfill_empty NETBOX_REDIS_PASSWORD 32 "$dry"
  backfill_empty NETBOX_REDIS_CACHE_PASSWORD 32 "$dry"
  backfill_empty NETBOX_SECRET_KEY 64 "$dry"
  backfill_empty NETBOX_API_TOKEN_PEPPER_1 64 "$dry"
  backfill_empty GRAFANA_ADMIN_PASSWORD 24 "$dry"
  backfill_empty GRAFANA_SECRET_KEY 48 "$dry"
  backfill_empty AP_ENCRYPTION_KEY 32 "$dry"
  backfill_empty AP_JWT_SECRET 48 "$dry"
  backfill_empty AP_POSTGRES_PASSWORD 32 "$dry"
  backfill_empty AP_REDIS_PASSWORD 32 "$dry"
  backfill_empty NETDISCO_DB_PASSWORD 32 "$dry"
  backfill_empty IE_DB_PASSWORD 32 "$dry"
  backfill_empty IE_CONFIG_DB_PASSWORD 32 "$dry"
}

# A pre-marker .env is an install when these keys were written by install.sh.
# .env.example leaves the secrets and INSTALL_DIR empty, so a copied example
# does not pass.
upgrade_env_is_real() {
  local key val
  for key in PUBLIC_HOST CLIENT_NAME CLIENT_SLUG INSTALL_DIR NETBOX_DB_PASSWORD NETBOX_SECRET_KEY; do
    val="$(getenv_val "$key")"
    [ -n "$val" ] || return 1
  done
  val="$(getenv_val PUBLIC_HOST)"
  printf '%s' "$val" | grep -Eq '^[A-Za-z0-9.:-]+$' || return 1
  return 0
}

# The old Oxidized default 400s until the tag exists. Any other non-empty
# filter, including one an operator set by hand, stays.
maybe_oxidized_filter() {
  local dry=$1 oxf
  oxf="$(getenv_val OXIDIZED_NETBOX_FILTER)"
  if [ -z "$oxf" ] || [ "$oxf" = "status=active&tag=oxidized" ]; then
    if [ "$dry" = 1 ]; then
      say "would set OXIDIZED_NETBOX_FILTER=status=active"
    else
      setenv OXIDIZED_NETBOX_FILTER "status=active"
      say "Oxidized backs up every active device (status=active). tag=oxidized is optional and 400s until that tag exists."
    fi
  fi
}

record_install_marker() {
  printf '%s\n' 'past-secret-generation' > .install-started
  chmod 600 .install-started
  grep -qx 'past-secret-generation' .install-started || die "could not record .install-started"
}

if [ "$RESUME" = 1 ] && [ "$WRITE_MARKER" = 1 ]; then
  if ! upgrade_env_is_real; then
    die "refusing --upgrade-env: .env must contain non-empty PUBLIC_HOST, CLIENT_NAME, CLIENT_SLUG, INSTALL_DIR, NETBOX_DB_PASSWORD, and NETBOX_SECRET_KEY, and PUBLIC_HOST must be a host name or IP. .env was not modified."
  fi
fi

if [ "$DRY_RUN" = 1 ]; then
  if [ "$WRITE_MARKER" = 1 ]; then
    say "pre-marker .env accepted for --upgrade-env"
    say "would write .install-started after backfill"
  else
    say "install marker present; would backfill empty secrets only"
  fi
  say "would leave PUBLIC_HOST, CLIENT_NAME, CLIENT_SLUG, INSTALL_DIR, ports, and existing certificates unchanged"
  backfill_required_secrets 1
  maybe_oxidized_filter 1
  exit 0
fi

if [ "$RESUME" = 1 ]; then
  if [ "$WRITE_MARKER" = 1 ]; then
    say "upgrading a pre-marker .env: filling missing secrets, then writing .install-started"
  else
    say "resuming install: secret generation already finished (.install-started). Continuing at certificates, image build, and start."
  fi
  # Every compose `:?run install.sh` secret. Only NETBOX_SUPERUSER_API_KEY is new
  # on an older .env; the rest are filled solely when they are blank.
  backfill_required_secrets 0
  maybe_oxidized_filter 0
  # The marker is written only after the backfill, so a failed fill can be retried.
  if [ "$WRITE_MARKER" = 1 ]; then
    record_install_marker
    say "wrote .install-started (past-secret-generation)"
  fi
  if [ "$PUBLIC_HOST_FROM_FLAG" = 1 ] || [ -n "${INSTALL_PUBLIC_HOST:-}" ] || [ "$PORTS" != auto ]; then
    warn "--public-host, INSTALL_PUBLIC_HOST, and port choices apply only when .env is first created; this run keeps the existing .env"
  fi
  PUBLIC_HOST="$(getenv_val PUBLIC_HOST)"
  [ -n "$PUBLIC_HOST" ] || die "PUBLIC_HOST is empty in the existing .env"
  printf '%s' "$PUBLIC_HOST" | grep -Eq '^[A-Za-z0-9.:-]+$' || die "host must contain only letters, digits, dots, colons or dashes"
else
  if [ -z "$PUBLIC_HOST" ]; then
    PUBLIC_HOST="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
    [ -n "$PUBLIC_HOST" ] || PUBLIC_HOST="$(hostname -f 2>/dev/null || hostname 2>/dev/null || true)"
    [ -n "$PUBLIC_HOST" ] || die "could not detect this host's address - pass --public-host"
    say "PUBLIC_HOST not given; using detected value '$PUBLIC_HOST' (override with --public-host)"
  fi
  printf '%s' "$PUBLIC_HOST" | grep -Eq '^[A-Za-z0-9.:-]+$' || die "host must contain only letters, digits, dots, colons or dashes"

  # Probe every published host port before writing .env. A busy default does not
  # force the whole alternative set (that set can itself be taken, e.g. 8443).
  plan_published_ports

  cp .env.example .env; chmod 600 .env
  ENV_CREATED=1

  setenv CLIENT_NAME "unconfigured"
  setenv CLIENT_SLUG "unconfigured"
  setenv INSTALL_DIR "$ROOT"
  setenv PUBLIC_HOST "$PUBLIC_HOST"
  setenv NETBOX_SUPERUSER_EMAIL "admin@${PUBLIC_HOST}"
  apply_port_plan

  setenv GRAFANA_ADMIN_PASSWORD "$(gen 24)"
  setenv GRAFANA_SECRET_KEY "$(gen 48)"
  setenv NETBOX_DB_PASSWORD "$(gen 32)"
  setenv NETBOX_REDIS_PASSWORD "$(gen 32)"
  setenv NETBOX_REDIS_CACHE_PASSWORD "$(gen 32)"
  setenv NETBOX_SECRET_KEY "$(gen 64)"
  setenv NETBOX_API_TOKEN_PEPPER_1 "$(gen 64)"
  setenv NETBOX_SUPERUSER_PASSWORD "$(gen 24)"
  # NetBox >= 4.5 v2 token: 12-character key + 40-character secret.
  setenv NETBOX_SUPERUSER_API_KEY "$(gen 12)"
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
    *) die "could not create a bcrypt hash for the admin basic-auth (need htpasswd, python3-bcrypt or docker). A partial .env is removed automatically; install one of those and re-run." ;;
  esac
  unset ADMIN_PW hash

  mkdir -p secrets
  # v2 token string clients send: nbt_<key>.<secret> (Authorization: Bearer).
  NB_TOKEN="nbt_$(getenv_val NETBOX_SUPERUSER_API_KEY).$(getenv_val NETBOX_SUPERUSER_API_TOKEN)"
  case "$NB_TOKEN" in
    nbt_*.*) ;;
    *) die "could not build the NetBox API token" ;;
  esac
  write_secret prometheus/netbox.token "$NB_TOKEN" 65534
  write_secret oxidized/netbox.token "$NB_TOKEN" 0
  write_secret cust-exporter/netbox.token "$NB_TOKEN" 0
  unset NB_TOKEN
  dedupe_env .env
  write_secret oxidized/device_username "" 0
  write_secret oxidized/device_password "" 0
  write_secret trapd/trap_community "" 10002
  write_secret trapd/v3_users.conf "" 10002
  for s in fortigate_token panos_api_key ise_credentials dnac_credentials sdwan_credentials; do
    write_secret "telegraf/$s" "" 10001
  done
  write_secret setup/token "$(gen 48)" 0
  [ "$PERM_WARN" = 1 ] && warn "not root: secret files for container users are mode 0644. Run 'sudo ./install.sh --fix-perms' to tighten them."

  record_install_marker
  ENV_CREATED=
fi

say "=== InsightEngine installer (no questions asked) ==="

mkdir -p certs secrets data/netdisco/logs data/migration data/setup migration cust-exporter/app config/netdisco/nd-site-local
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
say ""
if [ -f .env ]; then own_private_env .env; fi

say "=== done ==="
print_port_table
say "Configuration : .env (mode 600) holds the generated passwords. This script does not print them."
say "Certificates  : certs/ca.crt (private CA - import it into browsers that should trust this server)"
say "FIRST RUN     : open the setup URL above and paste the setup token."
say "                The token is in the file  secrets/setup/token  (read it yourself, e.g. 'sudo cat secrets/setup/token')."
say "                Then: client name, the first administrator email and password, then new install or move."
say "                The administrator password is chosen on that page. This script does not print it."
say "ONE CLONE     : this repository is the whole product (stack + UI under ui/). A second clone is not required."
say "Other        : API tokens (NetBox etc.): scripts/set-secret.sh <name> ; optional features: COMPOSE_PROFILES in .env"
