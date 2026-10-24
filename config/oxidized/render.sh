#!/bin/sh
# Renders Oxidized config + hook from templates (run by the oxidized-init
# container). Secrets are read from /run/secrets/* and never printed.
set -eu
umask 077
OUT=/out
T=/templates

# replace TOKEN with the content of env var named in $2 (safe for any chars)
subst() {  # subst <file> <TOKEN> <ENVVAR> [quote]
  f=$1 tok=$2 var=$3 q=${4:-no}
  V="$(printenv "$var" || true)" Q="$q" TOK="$tok" awk '
    BEGIN { v = ENVIRON["V"]; if (ENVIRON["Q"] == "yes") gsub(/\047/, "\047\047", v); key = ENVIRON["TOK"] }
    { line = $0; out = ""
      while ((i = index(line, key)) > 0) { out = out substr(line, 1, i - 1) v; line = substr(line, i + length(key)) }
      print out line }' "$f" > "$f.new"
  mv "$f.new" "$f"
}
read_secret() { tr -d '\r\n' < "/run/secrets/$1"; }

mkdir -p "$OUT/hooks" "$OUT/crashes"

cp "$T/config.tmpl" "$OUT/config"
export DEVICE_USERNAME DEVICE_PASSWORD NETBOX_TOKEN
DEVICE_USERNAME="$(read_secret device_username)"
DEVICE_PASSWORD="$(read_secret device_password)"
NETBOX_TOKEN="$(read_secret netbox_token)"
export INTERVAL="${OXIDIZED_INTERVAL:-14400}" THREADS="${OXIDIZED_THREADS:-60}"
export NETBOX_FILTER="${OXIDIZED_NETBOX_FILTER:-status=active&tag=oxidized}"
subst "$OUT/config" @@INTERVAL@@ INTERVAL
subst "$OUT/config" @@THREADS@@ THREADS
subst "$OUT/config" @@CLIENT_SLUG@@ CLIENT_SLUG
subst "$OUT/config" @@NETBOX_FILTER@@ NETBOX_FILTER
subst "$OUT/config" @@DEVICE_USERNAME@@ DEVICE_USERNAME yes
subst "$OUT/config" @@DEVICE_PASSWORD@@ DEVICE_PASSWORD yes
subst "$OUT/config" @@NETBOX_TOKEN@@ NETBOX_TOKEN yes

cp "$T/hooks/notify-change.sh.tmpl" "$OUT/hooks/notify-change.sh"
export ALERTMANAGER_URL=http://alertmanager:9093
subst "$OUT/hooks/notify-change.sh" @@ALERTMANAGER_URL@@ ALERTMANAGER_URL
subst "$OUT/hooks/notify-change.sh" @@CLIENT_SLUG@@ CLIENT_SLUG
chmod 755 "$OUT/hooks/notify-change.sh"

# The Oxidized image runs as this UID (TODO(Phindani): confirm for the pinned image).
chown -R "${OXIDIZED_UID:-30000}:${OXIDIZED_UID:-30000}" "$OUT"
chmod 600 "$OUT/config"
echo "oxidized config rendered"
