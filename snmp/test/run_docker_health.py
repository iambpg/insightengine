#!/usr/bin/env python3
"""Docker proof for health SNMP modules.

Runs snmpsim and snmp_exporter against the small multi-vendor fixture.
A Catalyst 9800 render is checked for the absence of inputs.snmp and is not
walked. Does not talk to a real controller.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "config" / "telegraf" / "wlc"))
from render_wlc import render  # noqa: E402

NET = "ie-health"
WORK = Path("/tmp/ie-health-test")
def run(cmd, **kwargs):
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=False, **kwargs)


def sh(cmd):
    return subprocess.check_output(cmd, text=True).strip()


def line(oid: str, kind: str, value: str) -> str:
    return "%s|%s|%s\n" % (oid, kind, value)


def write_small(path: Path) -> None:
    rows = []
    # IF-MIB, one critical-path interface.
    rows.append(line("1.3.6.1.2.1.2.2.1.2.1", "4", "Uplink"))
    rows.append(line("1.3.6.1.2.1.2.2.1.8.1", "2", "1"))
    rows.append(line("1.3.6.1.2.1.2.2.1.13.1", "65", "10"))
    rows.append(line("1.3.6.1.2.1.2.2.1.14.1", "65", "1"))
    rows.append(line("1.3.6.1.2.1.2.2.1.19.1", "65", "4"))
    rows.append(line("1.3.6.1.2.1.2.2.1.20.1", "65", "2"))
    rows.append(line("1.3.6.1.2.1.31.1.1.1.1.1", "4", "Te1/1/1"))
    rows.append(line("1.3.6.1.2.1.31.1.1.1.6.1", "70", "1000000"))
    rows.append(line("1.3.6.1.2.1.31.1.1.1.10.1", "70", "500000"))
    rows.append(line("1.3.6.1.2.1.31.1.1.1.15.1", "66", "10000"))
    rows.append(line("1.3.6.1.2.1.31.1.1.1.18.1", "4", "critical-path"))
    # Classic IOS memory and environment.
    rows.append(line("1.3.6.1.4.1.9.9.48.1.1.1.2.1", "4", "Processor"))
    rows.append(line("1.3.6.1.4.1.9.9.48.1.1.1.5.1", "66", "4000"))
    rows.append(line("1.3.6.1.4.1.9.9.48.1.1.1.6.1", "66", "6000"))
    rows.append(line("1.3.6.1.4.1.9.9.13.1.3.1.2.1", "4", "Inlet"))
    rows.append(line("1.3.6.1.4.1.9.9.13.1.3.1.3.1", "2", "42"))
    rows.append(line("1.3.6.1.4.1.9.9.13.1.3.1.6.1", "2", "1"))
    rows.append(line("1.3.6.1.4.1.9.9.13.1.4.1.2.1", "4", "Fan 1"))
    rows.append(line("1.3.6.1.4.1.9.9.13.1.4.1.3.1", "2", "1"))
    rows.append(line("1.3.6.1.4.1.9.9.13.1.5.1.2.1", "4", "PSU 1"))
    rows.append(line("1.3.6.1.4.1.9.9.13.1.5.1.3.1", "2", "1"))
    # IOS-XE memory, sensor, FRU. entPhysicalIndex 1 and 2.
    rows.append(line("1.3.6.1.2.1.47.1.1.1.1.7.1", "4", "Switch 1"))
    rows.append(line("1.3.6.1.2.1.47.1.1.1.1.2.1", "4", "Chassis"))
    rows.append(line("1.3.6.1.2.1.47.1.1.1.1.7.2", "4", "PSU 1"))
    rows.append(line("1.3.6.1.4.1.9.9.221.1.1.1.1.3.1.1", "4", "Processor"))
    rows.append(line("1.3.6.1.4.1.9.9.221.1.1.1.1.7.1.1", "66", "5000"))
    rows.append(line("1.3.6.1.4.1.9.9.221.1.1.1.1.8.1.1", "66", "5000"))
    rows.append(line("1.3.6.1.4.1.9.9.91.1.1.1.1.1.1", "2", "8"))
    rows.append(line("1.3.6.1.4.1.9.9.91.1.1.1.1.2.1", "2", "9"))
    rows.append(line("1.3.6.1.4.1.9.9.91.1.1.1.1.3.1", "2", "0"))
    rows.append(line("1.3.6.1.4.1.9.9.91.1.1.1.1.4.1", "2", "47"))
    rows.append(line("1.3.6.1.4.1.9.9.91.1.1.1.1.5.1", "2", "1"))
    rows.append(line("1.3.6.1.4.1.9.9.117.1.4.1.1.1.1", "2", "2"))
    rows.append(line("1.3.6.1.4.1.9.9.117.1.1.2.1.2.2", "2", "2"))
    # FortiGate sensor. Memory scalar stays on the fortigate module; include it
    # here so a health scrape still shows the OID the recording rule uses.
    rows.append(line("1.3.6.1.4.1.12356.101.4.1.4.0", "66", "41"))
    rows.append(line("1.3.6.1.4.1.12356.101.4.3.2.1.2.1", "4", "FAN 1"))
    rows.append(line("1.3.6.1.4.1.12356.101.4.3.2.1.3.1", "4", "4500"))
    rows.append(line("1.3.6.1.4.1.12356.101.4.3.2.1.4.1", "2", "0"))
    rows.append(line("1.3.6.1.4.1.12356.101.4.3.2.1.2.2", "4", "Temperature"))
    rows.append(line("1.3.6.1.4.1.12356.101.4.3.2.1.3.2", "4", "55"))
    rows.append(line("1.3.6.1.4.1.12356.101.4.3.2.1.4.2", "2", "0"))
    # Palo Alto memory and a celsius sensor.
    rows.append(line("1.3.6.1.2.1.25.2.3.1.3.1", "4", "Physical Memory"))
    rows.append(line("1.3.6.1.2.1.25.2.3.1.4.1", "2", "1024"))
    rows.append(line("1.3.6.1.2.1.25.2.3.1.5.1", "2", "1000000"))
    rows.append(line("1.3.6.1.2.1.25.2.3.1.6.1", "2", "400000"))
    rows.append(line("1.3.6.1.2.1.99.1.1.1.1.1", "2", "8"))
    rows.append(line("1.3.6.1.2.1.99.1.1.1.2.1", "2", "9"))
    rows.append(line("1.3.6.1.2.1.99.1.1.1.3.1", "2", "0"))
    rows.append(line("1.3.6.1.2.1.99.1.1.1.4.1", "2", "48"))
    rows.append(line("1.3.6.1.2.1.99.1.1.1.5.1", "2", "1"))
    # AireOS controller scalars and one AP so the count OID is distinct from the table.
    rows.append(line("1.3.6.1.4.1.14179.1.1.5.1.0", "2", "12"))
    rows.append(line("1.3.6.1.4.1.14179.1.1.5.2.0", "2", "8000000"))
    rows.append(line("1.3.6.1.4.1.14179.1.1.5.3.0", "2", "3000000"))
    rows.append(line("1.3.6.1.4.1.14179.1.1.3.2.0", "2", "1"))
    rows.append(line("1.3.6.1.4.1.14179.1.1.3.3.0", "2", "1"))
    rows.append(line("1.3.6.1.4.1.14179.1.1.3.4.0", "2", "0"))
    rows.append(line("1.3.6.1.4.1.14179.1.1.3.5.0", "2", "0"))
    rows.append(line("1.3.6.1.4.1.14179.2.3.5.1.1.0", "2", "120"))
    path.write_text("".join(rows))
    sort_snmprec(path)


def sort_snmprec(path: Path) -> None:
    lines = [row for row in path.read_text().splitlines() if row.strip()]
    lines.sort(key=lambda row: tuple(int(part) for part in row.split("|", 1)[0].split(".") if part))
    path.write_text("\n".join(lines) + "\n")


def wait_http(url: str, seconds: int = 60) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if response.status < 500:
                    return
        except Exception:
            time.sleep(1)
    raise SystemExit("timed out waiting for %s" % url)


def scrape(module: str) -> str:
    # Host network: a user-defined bridge did not return UDP replies to snmp_exporter.
    query = urllib.parse.urlencode({"target": "127.0.0.1:1161", "module": module, "auth": "ie_snmp_v2"})
    url = "http://127.0.0.1:19117/snmp?" + query
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            return response.read().decode("utf-8", "replace")
    except Exception as exc:
        return "ERROR %s" % exc


def main() -> int:
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir()
    small = WORK / "small" / "public.snmprec"
    small.parent.mkdir()
    write_small(small)

    run(["sudo", "docker", "rm", "-f", "snmp-health", "snmp-wlc", "snmp-exp", "snmp-health-host", "snmp-wlc-host", "snmp-exp-host"])

    def sim(port: str):
        return [
            "snmpsim-command-responder",
            "--data-dir=/data",
            "--agent-udpv4-endpoint=127.0.0.1:%s" % port,
            "--process-user=nobody",
            "--process-group=nogroup",
        ]

    run([
        "sudo", "docker", "run", "-d", "--name", "snmp-health", "--network", "host",
        "-v", "%s:/data:ro" % small.parent,
        "ie-snmpsim:local", *sim("1161"),
    ])
    run([
        "sudo", "docker", "run", "-d", "--name", "snmp-exp", "--network", "host",
        "-e", "SNMP_V2_COMMUNITY=public",
        "-e", "SNMP_V3_USERNAME=user",
        "-e", "SNMP_V3_AUTH_PASSWORD=authpass",
        "-e", "SNMP_V3_PRIV_PASSWORD=privpass",
        "-v", "%s:/etc/snmp_exporter/snmp.yml:ro" % (ROOT / "snmp" / "out" / "snmp.yml"),
        "-v", "%s:/snmp-exporter-run.sh:ro" % (ROOT / "config" / "snmp" / "snmp-exporter-run.sh"),
        "--entrypoint", "/bin/sh",
        "prom/snmp-exporter:v0.30.1",
        "/snmp-exporter-run.sh", "--web.listen-address=:19117",
    ])
    time.sleep(2)
    wait_http("http://127.0.0.1:19117/")
    ready = False
    for _ in range(40):
        body = scrape("cisco_wlc_aireos")
        if "bsnGlobalDot11SystemMobileStations" in body:
            ready = True
            break
        time.sleep(2)
    print("simulator ready" if ready else "simulator not ready")
    print(sh(["sudo", "docker", "logs", "--tail", "20", "snmp-health"]))

    expect = {
        "if_mib": "ifHCInOctets",
        "cisco_env": "ciscoEnvMonFanState",
        "cisco_mem": "ciscoMemoryPoolUsed",
        "cisco_enhanced_mem": "cempMemPoolUsed",
        "cisco_entity_sensor": "entSensorValue",
        "cisco_fru": "cefcFanTrayOperStatus",
        "fortinet_health": "fgHwSensorEntName",
        "paloalto_health": "hrStorageUsed",
        "cisco_wlc_aireos": "agentCurrentCPUUtilization",
        "cisco_cdp": "",
        "lldp": "",
    }
    failed = []
    for module, needle in expect.items():
        body = scrape(module)
        ok = body.startswith("#") or "snmp_" in body or needle in body
        if needle and needle not in body:
            ok = False
        print("MODULE", module, "OK" if ok else "FAIL", "bytes", len(body))
        if not ok:
            print(body[:500])
            failed.append(module)

    target = {
        "targets": ["127.0.0.1"],
        "labels": {
            "__meta_netbox_name": "wlc-9800",
            "__meta_netbox_platform": "ios-xe",
            "__meta_netbox_role": "wireless-controller",
            "__meta_netbox_site_name": "rotterdam",
            "__meta_netbox_snmp_auth": "ie_wlc_v2",
        },
    }
    conf = render([target], {"SNMP_V2_COMMUNITY": "public", "IE_WLC_LEGACY_SNMP": "1"})
    (WORK / "wlc-9800.conf").write_text(conf)
    if "inputs.snmp" in conf or "1.3.6.1.4.1.9.9.513" in conf:
        print("9800 render still has SNMP")
        failed.append("9800-render")
    else:
        print("9800 render has no inputs.snmp")

    summary = {"modules_failed": failed}
    (WORK / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
