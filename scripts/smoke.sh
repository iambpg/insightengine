#!/usr/bin/env bash
# After `docker compose up -d`, wait until every container for this project is
# healthy, a successful one-shot (exit 0), or running without a healthcheck.
# Prints the last 15 log lines of anything that is not. Does not start the stack.
#
#   ./scripts/smoke.sh              wait (SMOKE_TIMEOUT seconds, default 300)
#   ./scripts/smoke.sh --self-test  classifier only; Docker is not required
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ "${1:-}" = "--self-test" ]; then
  python3 - <<'PY'
import json, sys

def service_name(obj):
    name = obj.get("Service") or ""
    if name:
        return name
    labels = obj.get("Labels") or ""
    if isinstance(labels, dict):
        return labels.get("com.docker.compose.service") or obj.get("Name") or "unknown"
    for part in str(labels).split(","):
        if part.startswith("com.docker.compose.service="):
            return part.split("=", 1)[1]
    return obj.get("Name") or obj.get("Names") or "unknown"

def classify(obj):
    state = str(obj.get("State") or "").lower()
    health = str(obj.get("Health") or "").lower()
    try:
        code = int(obj.get("ExitCode"))
    except (TypeError, ValueError):
        code = None
    name = service_name(obj)
    if state == "exited" and code == 0:
        return "ok", name
    if state == "running" and health in ("", "healthy"):
        return "ok", name
    if state in ("restarting", "created") or (state == "running" and health == "starting"):
        return "wait", name
    return "fail", name

def parse_ps(text):
    text = text.strip()
    if not text:
        return []
    decoder = json.JSONDecoder()
    items = []
    idx = 0
    while idx < len(text):
        while idx < len(text) and text[idx].isspace():
            idx += 1
        if idx >= len(text):
            break
        obj, end = decoder.raw_decode(text, idx)
        if isinstance(obj, list):
            items.extend(obj)
        else:
            items.append(obj)
        idx = end
    return items

cases = [
    ({"Service": "caddy", "State": "running", "Health": "healthy", "ExitCode": 0}, "ok"),
    ({"Service": "prometheus", "State": "running", "Health": "", "ExitCode": 0}, "ok"),
    ({"Service": "netdisco-db-init", "State": "exited", "Health": "", "ExitCode": 0}, "ok"),
    ({"Service": "netdisco-db-role", "State": "exited", "ExitCode": 0}, "ok"),
    ({"Service": "oxidized-init", "State": "exited", "ExitCode": 0}, "ok"),
    ({"Service": "netbox", "State": "exited", "ExitCode": 1}, "fail"),
    ({"Service": "scrape-lb", "State": "running", "Health": "unhealthy", "ExitCode": 0}, "fail"),
    ({"Service": "caddy", "State": "running", "Health": "starting", "ExitCode": 0}, "wait"),
    ({"Service": "netbox", "State": "restarting", "ExitCode": 1}, "wait"),
    ({"Labels": "com.docker.compose.service=trapd,x=y", "State": "running", "Health": "healthy"}, "ok"),
]
for obj, want in cases:
    got, name = classify(obj)
    if got != want:
        raise SystemExit(f"classify {obj.get('Service') or name}: got {got}, want {want}")
    if obj.get("Labels") and name != "trapd":
        raise SystemExit(f"service name from label: {name}")

array = json.dumps([{"Service": "a", "State": "running", "Health": "healthy", "ExitCode": 0}])
lines = '{"Service":"a","State":"running","Health":"healthy","ExitCode":0}\n{"Service":"b","State":"exited","ExitCode":0}\n'
parsed_array = parse_ps(array)
parsed_lines = parse_ps(lines)
if len(parsed_array) != 1 or len(parsed_lines) != 2:
    raise SystemExit(f"parse_ps array={len(parsed_array)} lines={len(parsed_lines)}")
if classify(parsed_lines[1])[0] != "ok":
    raise SystemExit("json line one-shot was not ok")
print("PASS  smoke classifier")
PY
  exit 0
fi

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  sed -n '2,8p' "$0"
  exit 0
fi
if [ $# -gt 0 ]; then
  echo "ERROR: unknown argument: $1" >&2
  exit 2
fi

command -v docker >/dev/null 2>&1 || { echo "ERROR: docker is required" >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "ERROR: docker compose is required" >&2; exit 1; }

TIMEOUT="${SMOKE_TIMEOUT:-300}"
case "$TIMEOUT" in
  ''|*[!0-9]*) echo "ERROR: SMOKE_TIMEOUT must be a number of seconds" >&2; exit 2 ;;
esac

deadline=$((SECONDS + TIMEOUT))
while true; do
  raw="$(docker compose ps -a --format json 2>/dev/null || true)"
  ps_file="$(mktemp)"
  printf '%s' "$raw" > "$ps_file"
  report="$(python3 - "$ps_file" <<'PY'
import json, sys
text = open(sys.argv[1], encoding="utf-8").read()

def service_name(obj):
    name = obj.get("Service") or ""
    if name:
        return name
    labels = obj.get("Labels") or ""
    if isinstance(labels, dict):
        return labels.get("com.docker.compose.service") or obj.get("Name") or "unknown"
    for part in str(labels).split(","):
        if part.startswith("com.docker.compose.service="):
            return part.split("=", 1)[1]
    return obj.get("Name") or obj.get("Names") or "unknown"

def classify(obj):
    state = str(obj.get("State") or "").lower()
    health = str(obj.get("Health") or "").lower()
    try:
        code = int(obj.get("ExitCode"))
    except (TypeError, ValueError):
        code = None
    name = service_name(obj)
    detail = f"{state}/{health or '-'} exit={code if code is not None else '-'}"
    if state == "exited" and code == 0:
        return "ok", name, detail
    if state == "running" and health in ("", "healthy"):
        return "ok", name, detail
    if state in ("restarting", "created") or (state == "running" and health == "starting"):
        return "wait", name, detail
    return "fail", name, detail

def parse_ps(text):
    text = text.strip()
    if not text:
        return []
    decoder = json.JSONDecoder()
    items = []
    idx = 0
    while idx < len(text):
        while idx < len(text) and text[idx].isspace():
            idx += 1
        if idx >= len(text):
            break
        obj, end = decoder.raw_decode(text, idx)
        if isinstance(obj, list):
            items.extend(obj)
        else:
            items.append(obj)
        idx = end
    return items

rows = parse_ps(text)
if not rows:
    print("EMPTY")
    raise SystemExit
waiting = failing = 0
for obj in rows:
    verdict, name, detail = classify(obj)
    print(f"{verdict}\t{name}\t{detail}")
    if verdict == "wait":
        waiting += 1
    elif verdict == "fail":
        failing += 1
print(f"SUMMARY\t{waiting}\t{failing}\t{len(rows)}")
PY
)"
  rm -f "$ps_file"
  if [ "$report" = "EMPTY" ]; then
    echo "FAIL  no containers are up for this project" >&2
    exit 1
  fi
  summary="$(printf '%s\n' "$report" | awk -F '\t' '$1=="SUMMARY" { print $2, $3, $4 }')"
  waiting="${summary%% *}"
  rest="${summary#* }"
  failing="${rest%% *}"
  total="${rest#* }"
  if [ "$waiting" = 0 ] && [ "$failing" = 0 ]; then
    echo "PASS  ${total} containers (healthy, running, or one-shot exit 0)"
    exit 0
  fi
  if [ "$waiting" = 0 ] || [ "$SECONDS" -ge "$deadline" ]; then
    echo "FAIL  containers not healthy:" >&2
    printf '%s\n' "$report" | awk -F '\t' '$1=="fail" || $1=="wait" { printf "  %s  %s\n", $2, $3 }' >&2
    printf '%s\n' "$report" | awk -F '\t' '$1=="fail" || $1=="wait" { print $2 }' | sort -u | while IFS= read -r svc; do
      [ -n "$svc" ] || continue
      echo "----- $svc (last 15 log lines) -----" >&2
      docker compose logs --tail 15 --no-color "$svc" >&2 || true
    done
    exit 1
  fi
  sleep 5
done
