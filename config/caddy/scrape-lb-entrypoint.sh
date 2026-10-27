#!/bin/sh
# Copy the read-only Caddyfile and, only when the scale profile is up, add
# snmp-exporter-3/4 and blackbox-exporter-3. Those names do not exist otherwise,
# and Caddy's active health check would log a DNS error for each one.
# A parallel `docker compose up` may still be creating them, so retry briefly.
# NXDOMAIN returns immediately when the profile is off.
set -eu

cp /etc/caddy/Caddyfile /tmp/Caddyfile

found=0
if command -v nslookup >/dev/null 2>&1; then
  i=0
  while [ "$i" -lt 5 ]; do
    if nslookup snmp-exporter-3 >/dev/null 2>&1; then
      found=1
      break
    fi
    i=$((i + 1))
    sleep 1
  done
fi

if [ "$found" = 1 ]; then
  sed -i \
    -e 's#snmp-exporter-1:9116 snmp-exporter-2:9116#snmp-exporter-1:9116 snmp-exporter-2:9116 snmp-exporter-3:9116 snmp-exporter-4:9116#' \
    -e 's#blackbox-exporter-1:9115 blackbox-exporter-2:9115#blackbox-exporter-1:9115 blackbox-exporter-2:9115 blackbox-exporter-3:9115#' \
    /tmp/Caddyfile
fi

exec caddy run --config /tmp/Caddyfile --adapter caddyfile "$@"
