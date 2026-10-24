#!/bin/sh
# snmptrapd traphandle: stdin = hostname line, transport line, then
# "OID value" lines. Sends (1) an alert to Alertmanager, (2) a log line to Loki.
# Failures to deliver must never crash snmptrapd, so every send is best-effort.
AM="${ALERTMANAGER_URL:-http://alertmanager:9093}"
LOKI="${LOKI_URL:-http://loki:3100}"
TTL="${TRAP_ALERT_TTL_SECONDS:-3600}"
CLIENT="${CLIENT_SLUG:-unknown}"

read -r HOST_LINE || exit 0
read -r TRANSPORT || exit 0
# transport looks like: UDP: [192.0.2.7]:49152->[192.0.2.1]:162
IP=$(printf '%s' "$TRANSPORT" | sed -n 's/^[A-Za-z0-9]*: \[\([^]]*\)\].*/\1/p')
BODY_TXT=$(cat)
TRAP_OID=$(printf '%s\n' "$BODY_TXT" | awk '$1 ~ /snmpTrapOID\.0$/ {print $2; exit}')
[ -n "$TRAP_OID" ] || TRAP_OID="unknown"
NOW=$(date +%s)
START=$(date -u -d "@$NOW" +%Y-%m-%dT%H:%M:%SZ)
END=$(date -u -d "@$((NOW + TTL))" +%Y-%m-%dT%H:%M:%SZ)
LINE=$(printf 'host=%s ip=%s trap=%s | %s' "$HOST_LINE" "$IP" "$TRAP_OID" "$(printf '%s' "$BODY_TXT" | tr '\n' ';')")

jq -n --arg c "$CLIENT" --arg ip "${IP:-unknown}" --arg oid "$TRAP_OID" --arg host "$HOST_LINE" --arg s "$START" --arg e "$END" --arg line "$LINE" \
  '[{labels:{alertname:"SnmpTrap",severity:"warning",client:$c,instance:$ip,trap_oid:$oid,source:"snmptrap"},annotations:{summary:("SNMP trap " + $oid + " from " + $host),detail:$line},startsAt:$s,endsAt:$e}]' \
  | curl -fsS -m 5 -X POST -H 'Content-Type: application/json' -d @- "$AM/api/v2/alerts" >/dev/null 2>&1 || true

jq -n --arg c "$CLIENT" --arg ip "${IP:-unknown}" --arg ts "${NOW}000000000" --arg line "$LINE" \
  '{streams:[{stream:{job:"snmptrap",client:$c,instance:$ip},values:[[$ts,$line]]}]}' \
  | curl -fsS -m 5 -X POST -H 'Content-Type: application/json' -d @- "$LOKI/loki/api/v1/push" >/dev/null 2>&1 || true
exit 0
