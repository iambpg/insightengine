#!/usr/bin/env bash
# Static checks for the install-to-monitoring path, plus the live stack when Docker is up.
#
#   ./scripts/smoke-flow.sh
#   ./scripts/smoke-flow.sh --self-test
#
# Live stages (fresh install, login, device-type counts, approve) need a running
# stack and are skipped when the docker daemon is not available. They never print
# tokens or passwords.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
fail=0
ok() { printf 'PASS  %s\n' "$*"; }
bad() { printf 'FAIL  %s\n' "$*"; fail=1; }

python3 - <<'PY'
import pathlib, sys
root = pathlib.Path(".")
text = (root / "ui/src/app/device-list/components/DeviceTable.tsx").read_text()
if text.count("import { devicePath }") != 1:
    sys.exit("DeviceTable.tsx imports devicePath more than once")
lib = root / "netbox/device-types/library"
devices = list((lib / "device-types").rglob("*.yaml")) + list((lib / "device-types").rglob("*.yml"))
modules = list((lib / "module-types").rglob("*.yaml")) + list((lib / "module-types").rglob("*.yml"))
if len(devices) != 1288 or len(modules) != 571:
    sys.exit("device-type snapshot counts %s %s" % (len(devices), len(modules)))
source = (lib / "SOURCE").read_text()
if "6a2703f" not in source:
    sys.exit("SOURCE is not pinned")
compose = (root / "docker-compose.yml").read_text()
for needle in (
    "PGDATA: /var/lib/postgresql/data/pgdata",
    "start_period: 900s",
    "DANCER_ENVDIR: /home/netdisco/nd-site-local",
    "pull_policy: never",
    "SUPERUSER_API_KEY:",
    "netbox-device-types:",
    "netbox-regions:",
    "netbox-component-backfill:",
    "required: false",
):
    if needle not in compose:
        sys.exit("compose missing %s" % needle)
if "netbox-postgres-data:/var/lib/postgresql\n" in compose:
    sys.exit("netbox postgres still mounts the parent path")
prom = (root / "config/prometheus/prometheus.yml").read_text()
if "type: Bearer" not in prom or "type: Token" in prom:
    sys.exit("prometheus http_sd must use Bearer for NetBox 4.6 v2 tokens")
oxid = (root / "config/oxidized/config.tmpl").read_text()
if "Authorization: 'Bearer @@NETBOX_TOKEN@@'" not in oxid:
    sys.exit("oxidized must send Bearer")
print("snapshot and compose invariants ok")
PY
ok "static invariants"

if bash scripts/test-env-once.sh >/tmp/ie-env-once.out 2>&1; then
  ok "env keys once"
else
  bad "env keys once"
  cat /tmp/ie-env-once.out
fi

if command -v perl >/dev/null 2>&1; then
  if perl scripts/presweep.pl --self-test >/tmp/ie-presweep.out 2>&1; then
    ok "presweep self-test"
  else
    bad "presweep self-test"
    cat /tmp/ie-presweep.out
  fi
else
  echo "SKIP  presweep self-test (perl not installed)"
fi

if python3 -m py_compile netbox/device-types/import_device_types.py netbox/regions/import_regions.py netbox/component-backfill/backfill_components.py config-api/ie_config/discovery.py; then
  ok "python compile"
else
  bad "python compile"
fi

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  if [ "${1:-}" = "--live" ]; then
    echo "LIVE  run scripts/test-pg-persistence.sh and scripts/smoke.sh against a started stack"
    bash scripts/test-pg-persistence.sh
  else
    echo "SKIP  live install/approve (pass --live with the stack up; docker is available)"
  fi
else
  echo "SKIP  live install, health, setup, login, down/up, device-type import, and approve"
  echo "      docker is not available in this environment"
fi

exit "$fail"
