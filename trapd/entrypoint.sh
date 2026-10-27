#!/bin/sh
# Builds snmptrapd.conf from secret files (never printed), then runs snmptrapd
# in the foreground on UDP 1162 (published on host 162).
set -eu
umask 077
CONF=/var/lib/trapd/snmptrapd.conf
: > "$CONF"
if [ -s /run/secrets/trap_community ]; then
  comm="$(tr -d '\r\n' < /run/secrets/trap_community)"
  # community is written as a single token; reject whitespace
  case "$comm" in *[[:space:]]*|"") echo "invalid trap community" >&2; exit 1 ;; esac
  printf 'authCommunity log,execute %s\n' "$comm" >> "$CONF"
fi
if [ -s /run/secrets/trap_v3_users ]; then
  # lines in snmptrapd.conf syntax, e.g.:
  #   createUser -e 0x<engineID> <user> SHA <authpass> AES <privpass>
  #   authUser log,execute <user>
  cat /run/secrets/trap_v3_users >> "$CONF"
fi
# TRAP_HANDLER lets a directory mount of ./trapd replace the script baked into the image.
HANDLER="${TRAP_HANDLER:-/usr/local/bin/trap-handler.sh}"
case "$HANDLER" in
  *[!A-Za-z0-9_./-]*) echo "invalid TRAP_HANDLER" >&2; exit 1 ;;
esac
printf 'traphandle default %s\n' "$HANDLER" >> "$CONF"
export SNMPCONFPATH=/var/lib/trapd
exec snmptrapd -f -n -Lo -C -c "$CONF" -M /usr/share/snmp/mibs:/usr/share/snmp/mibs/custom -m ALL udp:1162
