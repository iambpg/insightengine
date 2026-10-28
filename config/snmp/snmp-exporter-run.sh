#!/bin/sh
# Prefer the generated runtime file (per-profile auths, mode 0600 on the host).
# When ie-config has not written one yet, keep the committed snmp.yml so the
# .env SNMP_* values remain the only credentials.
set -eu
cfg=/etc/snmp_exporter/snmp.yml
if [ -s /etc/ie-snmp/snmp.runtime.yml ]; then
  cfg=/etc/ie-snmp/snmp.runtime.yml
fi
bin=$(command -v snmp_exporter || true)
if [ -z "$bin" ]; then
  bin=/bin/snmp_exporter
fi
exec "$bin" --config.file="$cfg" "$@"
