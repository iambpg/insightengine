#!/usr/bin/env python3
"""Docker proof for health SNMP modules and a 5000-AP 9800 Telegraf walk.

Runs snmpsim, snmp_exporter and telegraf. Prints metric checks, walk duration
and series counts. Does not talk to a real controller.
"""

from __future__ import annotations

import json
import os
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
AP_COUNT = int(os.environ.get("IE_AP_COUNT", "5000"))
RADIOS = 2


def run(cmd, **kwargs):
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=False, **kwargs)


def sh(cmd):
    return subprocess.check_output(cmd, text=True).strip()


def mac_index(number: int) -> str:
    return "0.17.34.%d.%d.%d" % ((number >> 16) & 255, (number >> 8) & 255, number & 255)


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
    rows.append(line("1.3.6.1.4.1.9.9.513.1.3.35.0", "66", "2"))
    path.write_text("".join(rows))
    sort_snmprec(path)


def write_wlc(path: Path, count: int) -> None:
    # One joined-AP scalar plus the columns Telegraf actually walks.
    name_oid = "1.3.6.1.4.1.9.9.513.1.1.1.1.5"
    uptime_oid = "1.3.6.1.4.1.9.9.513.1.1.1.1.6"
    admin_oid = "1.3.6.1.4.1.9.9.513.1.1.1.1.38"
    clients_oid = "1.3.6.1.4.1.9.9.513.1.1.1.1.72"
    radio_oid = "1.3.6.1.4.1.9.9.513.1.2.1.1.2"
    channel_oid = "1.3.6.1.4.1.14179.2.2.2.1.4"
    util_oid = "1.3.6.1.4.1.14179.2.2.13.1.3"
    with path.open("w", encoding="utf-8") as handle:
        handle.write(line("1.3.6.1.4.1.9.9.513.1.3.35.0", "66", str(count)))
        for number in range(1, count + 1):
            index = mac_index(number)
            handle.write(line(name_oid + "." + index, "4", "ap-%05d" % number))
            handle.write(line(uptime_oid + "." + index, "67", str(100 * number)))
            handle.write(line(admin_oid + "." + index, "2", "1"))
            handle.write(line(clients_oid + "." + index, "66", str(number % 40)))
            for slot in range(RADIOS):
                radio = "%s.%d" % (index, slot)
                handle.write(line(radio_oid + "." + radio, "2", str(1 + slot)))
                handle.write(line(channel_oid + "." + radio, "2", str(36 if slot == 0 else 6)))
                handle.write(line(util_oid + "." + radio, "2", str((number + slot) % 80)))
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
    big = WORK / "wlc" / "public.snmprec"
    small.parent.mkdir()
    big.parent.mkdir()
    write_small(small)
    print("writing %d AP walk" % AP_COUNT, flush=True)
    write_wlc(big, AP_COUNT)
    print("walk bytes", big.stat().st_size, flush=True)

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
        "sudo", "docker", "run", "-d", "--name", "snmp-wlc", "--network", "host",
        "-v", "%s:/data:ro" % big.parent,
        "ie-snmpsim:local", *sim("1162"),
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
        body = scrape("cisco_wlc_iosxe")
        if "cLApGlobalAPConnectCount" in body:
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
        "cisco_wlc_iosxe": "cLApGlobalAPConnectCount",
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

    # 5000 AP walks, one table at a time, so duration is per table.
    results = []
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
    # snmp-wlc listens on 161 inside the network. render() writes udp://ip:161
    # so pass the docker DNS name as the address.
    for table in ("status", "clients", "radio", "channel"):
        conf = render([target], {"IE_WLC_TABLE": table, "SNMP_V2_COMMUNITY": "public"})
        conf = conf.replace("udp://127.0.0.1:161", "udp://127.0.0.1:1162")
        # Production staggers these tables. The timing run measures the walk, not the offset.
        conf = conf.replace('collection_offset = "180s"', 'collection_offset = "0s"')
        conf = conf.replace('collection_offset = "360s"', 'collection_offset = "0s"')
        conf = conf.replace('collection_offset = "480s"', 'collection_offset = "0s"')
        conf = conf.replace('collection_offset = "120s"', 'collection_offset = "0s"')
        conf = conf.replace('collection_offset = "240s"', 'collection_offset = "0s"')
        conf = conf.replace('collection_offset = "300s"', 'collection_offset = "0s"')
        path = WORK / ("wlc-%s.conf" % table)
        path.write_text(conf)
        started = time.time()
        proc = run([
            "sudo", "docker", "run", "--rm", "--network", "host",
            "-v", "%s:/etc/telegraf/wlc.conf:ro" % path,
            "--entrypoint", "telegraf",
            "telegraf:1.38.3",
            "--config", "/etc/telegraf/wlc.conf",
            "--test",
            "--non-strict-env-handling",
        ], capture_output=True, text=True)
        duration = time.time() - started
        text = (proc.stdout or "") + (proc.stderr or "")
        series = len([line for line in (proc.stdout or "").splitlines() if "ie_wlc_" in line])
        print("WALK", table, "seconds", round(duration, 1), "series", series, "exit", proc.returncode)
        if proc.returncode != 0:
            print(text[-800:])
        results.append({"table": table, "seconds": round(duration, 1), "series": series, "exit": proc.returncode})

    summary = {"modules_failed": failed, "aps": AP_COUNT, "walks": results}
    (WORK / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 1 if failed or any(item["exit"] != 0 for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
