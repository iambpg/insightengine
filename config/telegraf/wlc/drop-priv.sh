#!/bin/sh
# Copy root-only /run/secrets files for a service uid, then drop privileges.
#
# Compose file secrets are bind mounts. A host file that is root:root mode
# 0600 (or 0400 owned by a different uid) is not readable by the service
# user. This copies each secret to /run/ie-secrets mode 0400 owned by
# IE_RUN_UID:IE_RUN_GID and re-execs as that user. The host file is not
# changed and is not made world-readable.
#
# Telegraf (Debian) has GNU setpriv. Prometheus (busybox) has setuidgid.
# Usage: drop-priv.sh command [args...]
set -eu
umask 077

uid="${IE_RUN_UID:-10001}"
gid="${IE_RUN_GID:-10001}"

stage_secrets() {
  dest="${IE_SECRET_DIR:-/run/ie-secrets}"
  mkdir -p "$dest"
  chown "$uid:$gid" "$dest"
  chmod 0700 "$dest"
  if [ -d /run/secrets ]; then
    for src in /run/secrets/*; do
      [ -f "$src" ] || continue
      name=$(basename "$src")
      cp "$src" "$dest/$name"
      chown "$uid:$gid" "$dest/$name"
      chmod 0400 "$dest/$name"
    done
  fi
  if [ -f "$dest/netbox_token" ]; then
    case "${IE_NETBOX_TOKEN_FILE:-}" in
      ""|/run/secrets/netbox_token)
        export IE_NETBOX_TOKEN_FILE="$dest/netbox_token"
        ;;
    esac
  fi
}

drop_exec() {
  if setpriv --reuid="$uid" --regid="$gid" --clear-groups --inh-caps=-all true >/dev/null 2>&1; then
    exec setpriv --reuid="$uid" --regid="$gid" --clear-groups --inh-caps=-all "$@"
  fi
  if command -v setuidgid >/dev/null 2>&1; then
    if [ "$uid" != "$gid" ]; then
      echo "drop-priv: setuidgid cannot split uid $uid and gid $gid" >&2
      exit 1
    fi
    exec setuidgid "$uid" "$@"
  fi
  echo "drop-priv: no setpriv --reuid or setuidgid" >&2
  exit 1
}

if [ "$(id -u)" -eq 0 ]; then
  stage_secrets
  drop_exec "$0" "$@"
fi

if [ "$#" -eq 0 ]; then
  echo "drop-priv: nothing to exec" >&2
  exit 1
fi
exec "$@"
