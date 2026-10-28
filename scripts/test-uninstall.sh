#!/usr/bin/env bash
# Exercise scripts/uninstall.sh with a mocked docker. No daemon is required.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fail() { printf 'FAIL %s\n' "$*" >&2; exit 1; }

SECRET='db-password-should-not-appear'
ANON_NB='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
ANON_IE='bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
ANON_LABELLED='cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc'

make_fixture() {
  local dir=$1
  mkdir -p "$dir/scripts" "$dir/certs" "$dir/secrets" "$dir/data/migration" \
    "$dir/data/setup" "$dir/migration/imported" "$dir/config/netdisco/nd-site-local"
  cp "$ROOT/scripts/uninstall.sh" "$dir/scripts/uninstall.sh"
  cp "$ROOT/scripts/lib-compose-env.sh" "$dir/scripts/lib-compose-env.sh"
  chmod +x "$dir/scripts/uninstall.sh"
  printf '%s\n' 'name: insightengine' 'services: {}' > "$dir/docker-compose.yml"
  printf '%s\n' 'certs gitkeep' > "$dir/certs/.gitkeep"
  printf '%s\n' 'secrets gitkeep' > "$dir/secrets/.gitkeep"
  printf '%s\n' 'migration gitkeep' > "$dir/data/migration/.gitkeep"
  printf '%s\n' 'example deployment' > "$dir/config/netdisco/nd-site-local/deployment.yml.example"
  printf '%s\n' 'generated deployment' > "$dir/config/netdisco/nd-site-local/deployment.yml"
  printf '%s\n' 'cert bytes' > "$dir/certs/ca.crt"
  printf '%s\n' 'token bytes' > "$dir/secrets/token"
  printf '%s\n' 'old dump' > "$dir/data/migration/old.dump"
  printf '%s\n' '{}' > "$dir/data/setup/config.json"
  printf '%s\n' 'migrate conf' > "$dir/migration/migrate.conf"
  printf '%s\n' 'imported row' > "$dir/migration/imported/rows.txt"
  cat > "$dir/.env" <<EOF
PUBLIC_HOST='monitor.example'
CLIENT_SLUG='acme'
NETBOX_DB_PASSWORD='${SECRET}'
EOF
  printf '%s\n' 'past-secret-generation' > "$dir/.install-started"
  git -C "$dir" init -q
  git -C "$dir" -c user.email=test@example.com -c user.name=test add \
    docker-compose.yml certs/.gitkeep secrets/.gitkeep data/migration/.gitkeep \
    config/netdisco/nd-site-local/deployment.yml.example scripts/uninstall.sh scripts/lib-compose-env.sh
  git -C "$dir" -c user.email=test@example.com -c user.name=test commit -q -m init
}

make_docker() {
  local bin=$1
  mkdir -p "$bin"
  cat > "$bin/docker" <<'EOF'
#!/bin/bash
printf '%s\n' "$*" >> "$MOCK_LOG"
joined="$*"
case "$1" in
  info)
    if [ "${MOCK_DOCKER_DOWN:-0}" = 1 ]; then
      echo "${MOCK_DOCKER_ERR:-Cannot connect to the Docker daemon}" >&2
      exit 1
    fi
    exit 0
    ;;
  compose)
    printf '%s\n' '{"name":"insightengine"}'
    exit 0
    ;;
  ps)
    if [[ "$joined" != *com.docker.compose.project=insightengine* ]]; then
      printf '%s\n' 'k3s-pod'
      exit 0
    fi
    if [[ "$joined" == *insightengine-postgres* ]]; then
      if [ -f "$MOCK_DIR/no-ie" ]; then exit 0; fi
      printf '%s\n' 'cid-ie'
      exit 0
    fi
    if [[ "$joined" == *netbox-postgres* ]]; then
      printf '%s\n' 'cid-nb'
      exit 0
    fi
    if [[ "$joined" == *-aq* ]] || [[ "$joined" == *--format* ]]; then
      printf '%s\n' 'cid-nb netbox-postgres' 'cid-ie insightengine-postgres'
      exit 0
    fi
    printf '%s\n' 'k3s-pod'
    exit 0
    ;;
  inspect)
    id=""
    prev=""
    for a in "$@"; do
      if [ "$prev" != "-f" ]; then id=$a; fi
      prev=$a
    done
    if [[ "$joined" == *State.Status* ]]; then
      printf '%s\n' exited
      exit 0
    fi
    case "$id" in
      cid-nb)
        printf '%s\n' 'volume|aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa|/var/lib/postgresql/data'
        printf '%s\n' 'volume|insightengine_netbox-postgres-data|/var/lib/postgresql'
        ;;
      cid-ie)
        printf '%s\n' 'volume|bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb|/var/lib/postgresql/data'
        ;;
      *)
        echo "unexpected inspect $id" >&2
        exit 1
        ;;
    esac
    exit 0
    ;;
  volume)
    if [[ "$joined" == *volume\ ls* ]] || [[ "$2" == ls ]]; then
      if [[ "$joined" != *com.docker.compose.project=insightengine* ]]; then
        printf '%s\n' 'k3s-vol'
        exit 0
      fi
      printf '%s\n' insightengine_netbox-postgres-data cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      exit 0
    fi
    if [[ "$2" == rm ]]; then
      [ "${MOCK_VOLRM_FAIL:-0}" = 1 ] && exit 1
      exit 0
    fi
    echo "unexpected volume $*" >&2
    exit 1
    ;;
  network)
    if [[ "$2" == ls ]]; then
      if [[ "$joined" != *com.docker.compose.project=insightengine* ]]; then
        printf '%s\n' 'k3s-net'
        exit 0
      fi
      printf '%s\n' insightengine_monitoring-net
      exit 0
    fi
    if [[ "$2" == rm ]]; then
      exit 0
    fi
    echo "unexpected network $*" >&2
    exit 1
    ;;
  images)
    printf '%s\n' 'insightengine/ie-config:local' 'insightengine-ui:local' 'postgres:17.9' 'rancher/mirrored-pause:latest'
    exit 0
    ;;
  rmi)
    [ "${MOCK_RMI_FAIL:-0}" = 1 ] && exit 1
    exit 0
    ;;
  rm|start)
    exit 0
    ;;
  exec)
    printf '%s\n' 'PGDMP'
    exit 0
    ;;
  *)
    echo "unexpected docker $*" >&2
    exit 1
    ;;
esac
EOF
  # ANON ids are expanded by the parent shell into the mock via env, not this heredoc.
  # Rewrite the two mount lines after the heredoc so the mock sees the hex ids.
  :
  chmod +x "$bin/docker"
}

install_mock() {
  local bin=$1
  make_docker "$bin"
}

run_un() {
  local dir=$1
  shift
  env -u COMPOSE_PROJECT_NAME \
    PATH="$DOCKER_BIN:$PATH" \
    MOCK_LOG="$MOCK_LOG" \
    MOCK_DIR="$MOCK_STATE" \
    MOCK_DOCKER_DOWN="${MOCK_DOCKER_DOWN:-0}" \
    bash "$dir/scripts/uninstall.sh" "$@"
}

assert_no_secret() {
  local file=$1
  if grep -F -q "$SECRET" "$file"; then
    fail "secret appeared in $file"
  fi
}

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
fix="$tmp/fix"
bin="$tmp/bin"
MOCK_LOG="$tmp/docker.log"
MOCK_STATE="$tmp/state"
mkdir -p "$MOCK_STATE"
install_mock "$bin"
DOCKER_BIN="$bin"
make_fixture "$fix"

# Dry-run lists this project only and deletes nothing.
: > "$MOCK_LOG"
out="$tmp/dry.out"
run_un "$fix" >"$out"
assert_no_secret "$out"
assert_no_secret "$MOCK_LOG"
grep -q 'compose project: insightengine' "$out" || fail "project name"
grep -q 'cid-nb netbox-postgres' "$out" || fail "missing netbox container"
grep -q "$ANON_NB" "$out" || fail "missing anonymous postgres volume"
grep -q "$ANON_IE" "$out" || fail "missing ie anonymous volume"
grep -q 'insightengine_netbox-postgres-data' "$out" || fail "missing named volume"
grep -q "$ANON_LABELLED" "$out" || fail "missing labelled anonymous volume"
grep -q 'insightengine_monitoring-net' "$out" || fail "missing network"
grep -q 'insightengine/ie-config:local' "$out" || fail "missing ie-config image"
grep -q 'insightengine-ui:local' "$out" || fail "missing ui image"
grep -q 'certs/ca.crt' "$out" || fail "missing cert file"
grep -q 'secrets/token' "$out" || fail "missing secret file"
grep -q 'nd-site-local/deployment.yml' "$out" || fail "missing generated deployment"
grep -q 'migration/migrate.conf' "$out" || fail "missing migrate.conf"
grep -q 'sudo ./install.sh --public-host monitor.example' "$out" || fail "missing next step"
if grep -q 'k3s-pod' "$out" || grep -q 'k3s-vol' "$out" || grep -q 'k3s-net' "$out"; then
  fail "dry-run listed another project's docker resources"
fi
if grep -q 'postgres:17.9' "$out" || grep -q 'rancher/mirrored-pause' "$out"; then
  fail "dry-run listed an image that is not a local insightengine build"
fi
python3 - "$out" <<'PY'
import pathlib, sys
text = pathlib.Path(sys.argv[1]).read_text()
files = text.split("files:", 1)[1].split("kept:", 1)[0]
kept = text.split("kept:", 1)[1]
if "certs/.gitkeep" in files or "secrets/.gitkeep" in files or "docker-compose.yml" in files:
    raise SystemExit("tracked file listed for removal:\n" + files)
if "certs/.gitkeep" not in kept:
    raise SystemExit("tracked gitkeep was not kept")
PY
[ -f "$fix/.env" ] || fail "dry-run removed .env"
[ -f "$fix/certs/.gitkeep" ] || fail "dry-run removed gitkeep"
if grep -E -q '^(rm|rmi) ' "$MOCK_LOG" || grep -q 'volume rm' "$MOCK_LOG" || grep -q 'network rm' "$MOCK_LOG"; then
  fail "dry-run invoked docker removal"
fi
if grep -q 'com.docker.compose.project=k3s' "$MOCK_LOG"; then
  fail "queried a different compose project"
fi

# --apply without --yes and without a tty refuses.
set +e
refused="$(run_un "$fix" --apply </dev/null 2>&1)"
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "--apply without confirmation succeeded"
printf '%s\n' "$refused" | grep -q 'refusing to remove' || fail "missing refusal: $refused"
[ -f "$fix/.env" ] || fail "refused apply still removed .env"
assert_no_secret <(printf '%s\n' "$refused")

pty_apply() {
  local dir=$1 answer=$2
  DOCKER_BIN="$DOCKER_BIN" MOCK_LOG="$MOCK_LOG" MOCK_STATE="$MOCK_STATE" \
    python3 - "$dir" "$answer" <<'PY'
import os, pty, select, subprocess, sys
root, answer = sys.argv[1], sys.argv[2]
master, slave = pty.openpty()
env = os.environ.copy()
env["PATH"] = os.environ["DOCKER_BIN"] + os.pathsep + env.get("PATH", "")
env["MOCK_LOG"] = os.environ["MOCK_LOG"]
env["MOCK_DIR"] = os.environ["MOCK_STATE"]
env.pop("COMPOSE_PROJECT_NAME", None)
proc = subprocess.Popen(
    ["bash", os.path.join(root, "scripts", "uninstall.sh"), "--apply"],
    stdin=slave,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    env=env,
)
os.close(slave)
buf = b""
sent = False
while proc.poll() is None or not sent:
    ready, _, _ = select.select([master], [], [], 2)
    if master in ready:
        try:
            os.read(master, 4096)
        except OSError:
            pass
    chunk = b""
    if proc.stdout is not None:
        r2, _, _ = select.select([proc.stdout], [], [], 0.2)
        if r2:
            chunk = proc.stdout.read1(4096)
            if chunk:
                buf += chunk
    if not sent and (b"client slug" in buf or b"Type DELETE" in buf):
        os.write(master, (answer + "\n").encode())
        sent = True
    if proc.poll() is not None and not chunk:
        break
rest = proc.stdout.read() if proc.stdout is not None else b""
if rest:
    buf += rest
proc.wait(timeout=5)
sys.stdout.buffer.write(buf)
sys.exit(proc.returncode or 0)
PY
}

# Wrong confirmation removes nothing.
set +e
wrong="$(pty_apply "$fix" nope 2>&1)"
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "wrong confirmation succeeded: $wrong"
printf '%s\n' "$wrong" | grep -q 'did not match' || fail "wrong confirmation message: $wrong"
[ -f "$fix/.env" ] || fail "wrong confirmation removed .env"

# Slug confirmation removes install files and only this project's docker objects.
: > "$MOCK_LOG"
slug_out="$tmp/slug.out"
pty_apply "$fix" acme >"$slug_out"
assert_no_secret "$slug_out"
[ ! -e "$fix/.env" ] || fail ".env remains"
[ ! -e "$fix/.install-started" ] || fail "marker remains"
[ ! -e "$fix/certs/ca.crt" ] || fail "cert remains"
[ ! -e "$fix/secrets/token" ] || fail "secret file remains"
[ ! -e "$fix/data/setup/config.json" ] || fail "setup config remains"
[ ! -e "$fix/config/netdisco/nd-site-local/deployment.yml" ] || fail "generated deployment remains"
[ ! -e "$fix/migration/migrate.conf" ] || fail "migrate.conf remains"
[ -f "$fix/certs/.gitkeep" ] || fail "certs gitkeep removed"
[ -f "$fix/secrets/.gitkeep" ] || fail "secrets gitkeep removed"
[ -f "$fix/data/migration/.gitkeep" ] || fail "migration gitkeep removed"
[ -f "$fix/config/netdisco/nd-site-local/deployment.yml.example" ] || fail "example deployment removed"
[ -f "$fix/docker-compose.yml" ] || fail "compose file removed"
[ -f "$fix/scripts/uninstall.sh" ] || fail "uninstall script removed"
grep -q 'rm -f cid-nb cid-ie' "$MOCK_LOG" || grep -q 'rm -f cid-nb' "$MOCK_LOG" || fail "containers were not removed: $(cat "$MOCK_LOG")"
grep -q "volume rm" "$MOCK_LOG" || fail "volumes were not removed"
grep -q "$ANON_NB" "$MOCK_LOG" || fail "anonymous postgres volume was not removed"
grep -q 'insightengine_monitoring-net' "$MOCK_LOG" || fail "network was not removed"
grep -q '^rmi insightengine/ie-config:local' "$MOCK_LOG" || fail "ie-config image was not removed"
grep -q '^rmi insightengine-ui:local' "$MOCK_LOG" || fail "ui image was not removed"
if grep -q 'k3s' "$MOCK_LOG"; then
  # k3s may appear only if we queried without a filter. Removal lines must not name it.
  if grep -E '^(rm|rmi|volume rm|network rm).*k3s' "$MOCK_LOG"; then
    fail "removed a k3s resource"
  fi
fi
grep -q 'sudo ./install.sh --public-host monitor.example' "$slug_out" || fail "apply missing next step"

# Keep flags and a second fixture.
fix2="$tmp/fix2"
make_fixture "$fix2"
: > "$MOCK_LOG"
keep_out="$tmp/keep.out"
run_un "$fix2" --apply --yes --keep-images --keep-certs --keep-backups >"$keep_out"
assert_no_secret "$keep_out"
[ -f "$fix2/certs/ca.crt" ] || fail "--keep-certs removed the certificate"
[ -f "$fix2/data/migration/old.dump" ] || fail "--keep-backups removed the dump"
[ ! -e "$fix2/data/setup/config.json" ] || fail "setup config kept without --keep for that file"
[ ! -e "$fix2/.env" ] || fail ".env kept"
if grep -q '^rmi ' "$MOCK_LOG"; then
  fail "--keep-images still removed images"
fi

# Backup is written outside the fixture and a failed backup deletes nothing.
fix3="$tmp/fix3"
make_fixture "$fix3"
backups="$tmp/backups"
: > "$MOCK_LOG"
bak_out="$tmp/bak.out"
UNINSTALL_BACKUP_DIR="$backups" run_un "$fix3" --backup-first --apply --yes >"$bak_out"
assert_no_secret "$bak_out"
found="$(find "$backups" -name netbox.sql -o -name ie_config.sql | wc -l)"
[ "$found" -eq 2 ] || fail "expected two dump files, found $found"
if grep -R -F -q "$SECRET" "$backups"; then
  fail "secret stored in the backup directory listing or dump"
fi
grep -q 'PGDMP' "$backups"/*/netbox.sql || fail "netbox dump missing"
[ "$(stat -c %a "$backups"/uninstall-*)" = 700 ] || fail "backup directory is not owner-only"
[ "$(stat -c %a "$backups"/uninstall-*/netbox.sql)" = 600 ] || fail "dump is not owner-only"
[ ! -e "$fix3/.env" ] || fail "backup apply left .env"

fix4="$tmp/fix4"
make_fixture "$fix4"
: > "$MOCK_LOG"
touch "$MOCK_STATE/no-ie"
set +e
bak_fail="$(UNINSTALL_BACKUP_DIR="$tmp/backups2" run_un "$fix4" --backup-first --apply --yes 2>&1)"
rc=$?
set -e
rm -f "$MOCK_STATE/no-ie"
[ "$rc" -ne 0 ] || fail "failed backup still exited 0"
printf '%s\n' "$bak_fail" | grep -q 'nothing was removed' || fail "failed backup did not abort: $bak_fail"
[ -f "$fix4/.env" ] || fail "failed backup removed .env"

# Docker daemon down: the wipe is refused, because removing only the files would leave
# volumes that hold the old passwords. The dry-run still works.
fix5="$tmp/fix5"
make_fixture "$fix5"
: > "$MOCK_LOG"
set +e
down_msg="$(MOCK_DOCKER_DOWN=1 run_un "$fix5" --apply --yes 2>&1)"
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "apply with Docker down succeeded"
printf '%s\n' "$down_msg" | grep -q 'nothing was removed' || fail "docker-down refusal message: $down_msg"
printf '%s\n' "$down_msg" | grep -q 'daemon is not running' || fail "docker-down reason missing: $down_msg"
[ -f "$fix5/.env" ] || fail "docker-down refusal removed .env"
perm_msg="$(MOCK_DOCKER_DOWN=1 MOCK_DOCKER_ERR='permission denied while trying to connect' run_un "$fix5" --apply --yes 2>&1 || true)"
printf '%s\n' "$perm_msg" | grep -q 'run with sudo' || fail "permission-denied hint missing: $perm_msg"
MOCK_DOCKER_DOWN=1 run_un "$fix5" >"$tmp/down-dry.out" 2>/dev/null || fail "dry-run with Docker down failed"
[ -f "$fix5/.env" ] || fail "dry-run removed .env"
# --files-only removes just the files and never calls docker.
: > "$MOCK_LOG"
MOCK_DOCKER_DOWN=1 run_un "$fix5" --apply --yes --files-only >"$tmp/fo.out" 2>"$tmp/fo.err" || fail "--files-only failed"
[ ! -e "$fix5/.env" ] || fail "--files-only left .env"
if grep -E -q '^(ps|volume|network|rmi|rm) ' "$MOCK_LOG"; then
  fail "--files-only queried or removed docker objects"
fi

# A volume that cannot be removed keeps the files, so a fresh install cannot reuse old data.
fixv="$tmp/fixv"
make_fixture "$fixv"
set +e
vol_msg="$(MOCK_VOLRM_FAIL=1 run_un "$fixv" --apply --yes 2>&1)"
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "apply succeeded although volumes could not be removed"
printf '%s\n' "$vol_msg" | grep -q 'files were kept' || fail "volume failure message: $vol_msg"
[ -f "$fixv/.env" ] || fail "volume failure removed .env"
# An image that cannot be removed does not stop the wipe, but the exit status says so.
fixi="$tmp/fixi"
make_fixture "$fixi"
set +e
img_msg="$(MOCK_RMI_FAIL=1 run_un "$fixi" --apply --yes 2>&1)"
rc=$?
set -e
[ "$rc" -eq 1 ] || fail "image failure exit status $rc"
[ ! -e "$fixi/.env" ] || fail "image failure left .env"
printf '%s\n' "$img_msg" | grep -q 'could not be removed' || fail "image failure message: $img_msg"

# Files this user cannot remove abort before anything is deleted (skipped when running as root).
if [ "$(id -u)" -ne 0 ]; then
  fixp="$tmp/fixp"
  make_fixture "$fixp"
  mkdir -p "$fixp/data/locked"
  printf '%s\n' x > "$fixp/data/locked/file"
  chmod 500 "$fixp/data/locked"
  set +e
  lock_msg="$(run_un "$fixp" --apply --yes 2>&1)"
  rc=$?
  set -e
  chmod 700 "$fixp/data/locked"
  [ "$rc" -ne 0 ] || fail "apply succeeded with a directory this user cannot clean"
  printf '%s\n' "$lock_msg" | grep -q 'nothing was removed' || fail "locked directory message: $lock_msg"
  [ -f "$fixp/.env" ] || fail "locked directory run removed .env"
  chmod 000 "$fixp/data/locked"
  hid_msg="$(run_un "$fixp" --apply --yes 2>&1 || true)"
  chmod 700 "$fixp/data/locked"
  printf '%s\n' "$hid_msg" | grep -q 'cannot read' || fail "unreadable directory not reported: $hid_msg"
  [ -f "$fixp/.env" ] || fail "unreadable directory run removed .env"
fi

# No docker binary at all: --files-only is the only way to wipe. PATH holds every tool the
# script needs except docker.
fix6="$tmp/fix6"
make_fixture "$fix6"
nobin="$tmp/nobin"
mkdir -p "$nobin"
for tool in bash env git find sed awk grep dirname cat date stat rm rmdir mkdir tr cut head sort ls id printf; do
  path="$(command -v "$tool" || true)"
  [ -n "$path" ] && [ -x "$path" ] && ln -sf "$path" "$nobin/$tool"
done
set +e
nodocker_msg="$(PATH="$nobin" "$nobin/bash" "$fix6/scripts/uninstall.sh" --apply --yes 2>&1)"
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "no-docker apply succeeded"
printf '%s\n' "$nodocker_msg" | grep -q 'not found' || fail "no-docker reason missing: $nodocker_msg"
nodocker="$(PATH="$nobin" "$nobin/bash" "$fix6/scripts/uninstall.sh" --apply --yes --files-only 2>&1)" || fail "no-docker --files-only failed"
[ ! -e "$fix6/.env" ] || fail "no-docker --files-only left .env"
assert_no_secret <(printf '%s\n' "$nodocker")

# Second apply on an already-clean tree succeeds.
clean_out="$(run_un "$fix6" --apply --yes 2>/dev/null || true)"
printf '%s\n' "$clean_out" | grep -q 'compose project: insightengine' || fail "second apply did not finish"

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  echo "NOTE  a Docker daemon is available; this test still used a mock and did not remove real containers"
else
  echo "SKIP  live Docker daemon: uninstall was not run against a real daemon. Containers, volumes, networks, and images were simulated."
fi
echo "PASS  uninstall dry-run, confirmation, project filter, keep flags, backup, Docker-down refusal, --files-only, and partial-failure paths"
