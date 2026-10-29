#!/bin/sh
# Config layering for snmp_exporter:
#   1. the committed snmp.yml (modules plus the .env based auths), with
#      "community: ${VAR}" resolved from the environment. snmp_exporter only
#      expands env vars in username/password/priv_password, never in
#      community, so a literal ${SNMP_V2_COMMUNITY} would be sent on the wire.
#   2. the generated runtime file from ie-config (per-profile auths, mode 0600
#      on the host). It is always passed, even when it does not exist yet:
#      snmp_exporter globs --config.file and only warns for a missing file, so
#      a later POST /-/reload picks it up. Choosing the path once at start-up
#      would pin an exporter that started first to the committed file forever.
# Later files override earlier auths with the same name.
set -eu
base=/etc/snmp_exporter/snmp.yml
resolved=/tmp/snmp.base.yml
umask 077
awk '
function jq(s,   i, c, out) {
  out = ""
  for (i = 1; i <= length(s); i++) {
    c = substr(s, i, 1)
    if (c == "\\" || c == "\"") out = out "\\"
    out = out c
  }
  return "\"" out "\""
}
{
  if (match($0, /^[ \t]+community:[ \t]*\$\{[A-Za-z_][A-Za-z0-9_]*\}[ \t]*$/)) {
    name = $0
    sub(/^[ \t]+community:[ \t]*\$\{/, "", name)
    sub(/\}[ \t]*$/, "", name)
    indent = $0
    sub(/community:.*$/, "", indent)
    if (name in ENVIRON) { print indent "community: " jq(ENVIRON[name]); next }
  }
  print
}' "$base" > "$resolved"
bin=$(command -v snmp_exporter || true)
if [ -z "$bin" ]; then
  bin=/bin/snmp_exporter
fi
exec "$bin" --config.file="$resolved" --config.file=/etc/ie-snmp/snmp.runtime.yml "$@"
