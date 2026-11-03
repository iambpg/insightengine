#!/usr/bin/env python3
"""Docker proof for service experience. No real 9800, cEdge or bank is contacted.

- Telegraf cisco_telemetry_mdt receives a simulated gRPC dial-out and the
  starlark processor aggregates two clients onto one radio.
- snmp_exporter walks CISCO-RTTMON-MIB and CISCO-IETF-BFD-MIB on snmpsim.
- blackbox probes a local ICMP target and a local TCP listener.
- Prometheus loads mock NetBox HTTP SD.
- promtool checks the experience rules.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import textwrap
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _sd():
    import importlib.util
    path = ROOT / "netbox" / "netbox_lists" / "sd.py"
    spec = importlib.util.spec_from_file_location("netbox_lists_sd_docker", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

WORK = Path("/tmp/ie-experience")
SIM_IMAGE = "ie-snmpsim:local"


def run(cmd, **kwargs):
    print("+", " ".join(str(part) for part in cmd), flush=True)
    return subprocess.run(cmd, check=False, **kwargs)


def sh(cmd):
    return subprocess.check_output(cmd, text=True).strip()


def line(oid: str, kind: str, value: str) -> str:
    return "%s|%s|%s\n" % (oid, kind, value)


def sort_snmprec(path: Path) -> None:
    rows = [row for row in path.read_text().splitlines() if row.strip()]
    rows.sort(key=lambda row: tuple(int(part) for part in row.split("|", 1)[0].split(".") if part))
    path.write_text("\n".join(rows) + "\n")


def write_sim(path: Path) -> None:
    rows = []
    # IP SLA tcp-connect index 1001 and udp-jitter index 1002.
    rows.append(line("1.3.6.1.4.1.9.9.42.1.2.1.1.3.1001", "4", "vbs-tcp"))
    rows.append(line("1.3.6.1.4.1.9.9.42.1.2.1.1.4.1001", "2", "6"))
    rows.append(line("1.3.6.1.4.1.9.9.42.1.2.10.1.1.1001", "66", "25"))
    rows.append(line("1.3.6.1.4.1.9.9.42.1.2.10.1.2.1001", "2", "1"))
    rows.append(line("1.3.6.1.4.1.9.9.42.1.2.1.1.3.1002", "4", "vbs-udp-jitter"))
    rows.append(line("1.3.6.1.4.1.9.9.42.1.2.1.1.4.1002", "2", "9"))
    rows.append(line("1.3.6.1.4.1.9.9.42.1.5.2.1.1.1002", "66", "20"))
    rows.append(line("1.3.6.1.4.1.9.9.42.1.5.2.1.26.1002", "66", "1"))
    rows.append(line("1.3.6.1.4.1.9.9.42.1.5.2.1.27.1002", "66", "0"))
    rows.append(line("1.3.6.1.4.1.9.9.42.1.5.2.1.46.1002", "66", "4"))
    # Hourly jitter stats, index 1002 and a start time of 1.
    rows.append(line("1.3.6.1.4.1.9.9.42.1.3.5.1.34.1002.1", "65", "3"))
    rows.append(line("1.3.6.1.4.1.9.9.42.1.3.5.1.62.1002.1", "66", "5"))
    # BFD session 1 is up (4). This MIB has no loss, latency or jitter.
    rows.append(line("1.3.6.1.4.1.9.10.137.1.2.1.6.1", "2", "4"))
    path.write_text("".join(rows))
    sort_snmprec(path)


def wait_sim(name: str = "ie-exp-sim", seconds: int = 30) -> None:
    # snmpsim writes its listen line to stderr. docker logs keeps that stream
    # separate, so merge it or the wait never sees the line.
    deadline = time.time() + seconds
    while time.time() < deadline:
        logs = subprocess.check_output(
            ["sudo", "docker", "logs", name],
            text=True,
            stderr=subprocess.STDOUT,
        )
        if "Listening at UDP" in logs:
            return
        time.sleep(0.3)
    raise SystemExit("timed out waiting for %s to listen" % name)


def wait_http(url: str, seconds: int = 40) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return
        except Exception:
            time.sleep(0.5)
    raise SystemExit("timed out waiting for %s" % url)


def http_text(url: str, timeout: int = 30) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def ensure_sim_image() -> None:
    probe = run(["sudo", "docker", "image", "inspect", SIM_IMAGE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if probe.returncode == 0:
        return
    docker = WORK / "snmpsim.Dockerfile"
    docker.write_text(textwrap.dedent("""\
        FROM python:3.11-slim
        RUN pip install --no-cache-dir 'snmpsim==1.1.7'
        ENTRYPOINT ["snmpsim-command-responder"]
    """))
    built = run(["sudo", "docker", "build", "-t", SIM_IMAGE, "-f", str(docker), str(WORK)])
    if built.returncode != 0:
        raise SystemExit("could not build snmpsim")


def fast_telegraf() -> Path:
    text = (ROOT / "config" / "telegraf" / "wlc" / "telegraf.conf").read_text()
    text = text.replace('flush_interval = "30s"', 'flush_interval = "1s"')
    path = WORK / "telegraf.conf"
    path.write_text(text)
    return path


class SdHandler(BaseHTTPRequestHandler):
    services = []
    sites = []

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if parsed.path.startswith("/services"):
            body = _sd().service_targets(
                self.services,
                (query.get("tag") or [""])[0],
                (query.get("probe") or [""])[0],
            )
        elif parsed.path.startswith("/vbs"):
            body = _sd().vbs_targets(self.sites)
        else:
            body = []
        raw = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt, *args):
        return


def main() -> int:
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir()
    failed = []
    data = WORK / "sim"
    data.mkdir()
    write_sim(data / "public.snmprec")
    ensure_sim_image()
    run(["sudo", "docker", "rm", "-f", "ie-exp-sim", "ie-exp-snmp", "ie-exp-bb", "ie-exp-prom", "ie-exp-mdt"])

    run([
        "sudo", "docker", "run", "-d", "--name", "ie-exp-sim", "--network", "host",
        "-v", "%s:/data:ro" % data,
        SIM_IMAGE,
        "--data-dir=/data", "--agent-udpv4-endpoint=127.0.0.1:1165",
        "--process-user=nobody", "--process-group=nogroup",
    ])
    wait_sim()
    run([
        "sudo", "docker", "run", "-d", "--name", "ie-exp-snmp", "--network", "host",
        "-e", "SNMP_V2_COMMUNITY=public",
        "-e", "SNMP_V3_USERNAME=user",
        "-e", "SNMP_V3_AUTH_PASSWORD=authpass",
        "-e", "SNMP_V3_PRIV_PASSWORD=privpass",
        "-v", "%s:/etc/snmp_exporter/snmp.yml:ro" % (ROOT / "snmp" / "out" / "snmp.yml"),
        "-v", "%s:/snmp-exporter-run.sh:ro" % (ROOT / "config" / "snmp" / "snmp-exporter-run.sh"),
        "--entrypoint", "/bin/sh",
        "prom/snmp-exporter:v0.30.1",
        "/snmp-exporter-run.sh", "--web.listen-address=:19118",
    ])
    tcp = socket.socket()
    tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tcp.bind(("127.0.0.1", 19991))
    tcp.listen(8)
    run([
        "sudo", "docker", "run", "-d", "--name", "ie-exp-bb", "--network", "host", "--cap-add", "NET_RAW",
        "-v", "%s:/etc/blackbox/blackbox.yml:ro" % (ROOT / "config" / "blackbox" / "blackbox.yml"),
        "prom/blackbox-exporter:v0.28.0",
        "--config.file=/etc/blackbox/blackbox.yml", "--web.listen-address=:19115",
    ])
    wait_http("http://127.0.0.1:19118/")
    wait_http("http://127.0.0.1:19115/")

    def scrape(module: str) -> str:
        query = urllib.parse.urlencode({"target": "127.0.0.1:1165", "module": module, "auth": "ie_snmp_v2"})
        try:
            return http_text("http://127.0.0.1:19118/snmp?" + query, timeout=40)
        except Exception as exc:
            return "ERROR %s" % exc

    rtt = scrape("cisco_rttmon")
    print("RTTMON bytes", len(rtt))
    for needle in (
        "rttMonLatestRttOperCompletionTime",
        'rttMonCtrlAdminTag="vbs-tcp"',
        "rttMonLatestJitterOperAvgJitter",
        "rttMonLatestJitterOperPacketLossSD",
        "rttMonJitterStatsAvgJitter",
    ):
        if needle not in rtt:
            print(rtt[:800])
            failed.append("rttmon:%s" % needle)
    bfd = scrape("cisco_sdwan_bfd")
    if "ciscoBfdSessState" not in bfd or "4" not in bfd:
        print(bfd[:500])
        failed.append("bfd")
    else:
        print("BFD session state present")

    icmp = http_text("http://127.0.0.1:19115/probe?module=icmp&target=127.0.0.1", timeout=20)
    tcp_body = http_text("http://127.0.0.1:19115/probe?module=tcp_connect&target=127.0.0.1:19991", timeout=20)
    if "probe_success 1" not in icmp:
        print(icmp[:400])
        failed.append("blackbox-icmp")
    if "probe_success 1" not in tcp_body:
        print(tcp_body[:400])
        failed.append("blackbox-tcp")
    else:
        print("blackbox icmp and tcp_connect succeeded")

    SdHandler.services = [{
        "name": "lab-bank",
        "tags": ["bank"],
        "probe": "tcp",
        "address": "127.0.0.1",
        "port": "19991",
        "site": "lab",
    }]
    SdHandler.sites = [{"name": "lab", "vbs_server_ip": "127.0.0.1", "vbs_server_port": 9999}]
    server = ThreadingHTTPServer(("127.0.0.1", 18991), SdHandler)
    import threading
    threading.Thread(target=server.serve_forever, daemon=True).start()
    prom = WORK / "prometheus.yml"
    prom.write_text(textwrap.dedent("""\
        global:
          scrape_interval: 5s
        scrape_configs:
          - job_name: blackbox-bank-tcp
            metrics_path: /probe
            params:
              module: [tcp_connect]
            http_sd_configs:
              - url: http://127.0.0.1:18991/services?tag=bank&probe=tcp
                refresh_interval: 5s
            relabel_configs:
              - source_labels: [__address__]
                target_label: __param_target
              - source_labels: [__param_target]
                target_label: instance
              - source_labels: [__meta_netbox_name]
                target_label: name
              - source_labels: [__meta_netbox_kind]
                target_label: target_kind
              - target_label: __address__
                replacement: 127.0.0.1:19115
          - job_name: blackbox-vbs-icmp
            metrics_path: /probe
            params:
              module: [icmp]
            http_sd_configs:
              - url: http://127.0.0.1:18991/vbs
                refresh_interval: 5s
            relabel_configs:
              - source_labels: [__address__]
                target_label: __param_target
              - source_labels: [__meta_netbox_site_name]
                target_label: site
              - source_labels: [__meta_netbox_kind]
                target_label: target_kind
              - target_label: __address__
                replacement: 127.0.0.1:19115
    """))
    run([
        "sudo", "docker", "run", "-d", "--name", "ie-exp-prom", "--network", "host",
        "-v", "%s:/etc/prometheus/prometheus.yml:ro" % prom,
        "prom/prometheus:v3.11.3",
        "--config.file=/etc/prometheus/prometheus.yml",
        "--web.listen-address=:19090",
        "--storage.tsdb.path=/tmp/prom",
    ])
    rules = run([
        "sudo", "docker", "run", "--rm",
        "-v", "%s:/rules:ro" % (ROOT / "config" / "prometheus"),
        "--entrypoint", "promtool",
        "prom/prometheus:v3.11.3",
        "check", "rules", "/rules/experience-rules.yml",
    ])
    if rules.returncode != 0:
        failed.append("promtool")
    else:
        print("promtool accepted experience-rules.yml")

    wait_http("http://127.0.0.1:19090/-/ready", 50)
    seen = ""
    deadline = time.time() + 40
    while time.time() < deadline:
        try:
            seen = http_text("http://127.0.0.1:19090/api/v1/targets")
        except Exception:
            time.sleep(1)
            continue
        if "lab-bank" in seen and '"health":"up"' in seen:
            break
        time.sleep(2)
    if "lab-bank" not in seen:
        print(seen[:800])
        failed.append("http-sd")
    else:
        print("prometheus discovered the mock bank target")

    conf = fast_telegraf()
    mdt = run([
        "sudo", "docker", "run", "-d", "--name", "ie-exp-mdt", "--network", "host",
        "-e", "CLIENT_SLUG=lab",
        "-e", "IE_WLC_STORE_CLIENTS=0",
        "-e", "IE_MDT_PORT=57500",
        "-v", "%s:/etc/telegraf/telegraf.conf:ro" % conf,
        "-v", "%s:/etc/telegraf/mdt.conf:ro" % (ROOT / "config" / "telegraf" / "wlc" / "mdt.conf"),
        "-v", "%s:/etc/telegraf/normalize.star:ro" % (ROOT / "config" / "telegraf" / "wlc" / "normalize.star"),
        "telegraf:1.38.3",
        "--config", "/etc/telegraf/telegraf.conf",
        "--config", "/etc/telegraf/mdt.conf",
        "--non-strict-env-handling",
    ])
    if mdt.returncode != 0:
        failed.append("telegraf-start")
    else:
        time.sleep(3)
        logs = sh(["sudo", "docker", "logs", "ie-exp-mdt"])
        if "Error" in logs and "starlark" in logs.lower():
            print(logs[-1500:])
            failed.append("starlark")
        else:
            send = run([sys.executable, str(ROOT / "snmp" / "test" / "mdt_send.py")], cwd=str(WORK))
            if send.returncode != 0:
                failed.append("mdt-send")
            else:
                body = ""
                deadline = time.time() + 20
                while time.time() < deadline:
                    try:
                        body = http_text("http://127.0.0.1:9273/metrics")
                    except Exception:
                        time.sleep(1)
                        continue
                    if "ie_wlc_client_radio_clients" in body and "ie_sdwan_tunnel_loss_ratio" in body:
                        break
                    time.sleep(1)
                print("MDT metrics bytes", len(body))
                if "aa:bb:cc:dd:ee:01" in body or "aa:bb:cc:dd:ee:02" in body:
                    failed.append("client-mac-stored")
                if "ie_wlc_client_radio_clients" not in body:
                    print(sh(["sudo", "docker", "logs", "--tail", "80", "ie-exp-mdt"]))
                    print(body[:1000])
                    failed.append("mdt-clients")
                if "ie_sdwan_tunnel_latency_ms" not in body:
                    failed.append("mdt-sdwan")
                if "ie_wlc_radio_channel_util" not in body:
                    failed.append("mdt-rrm")
                if 'ie_wlc_ap_oper_up' not in body:
                    failed.append("mdt-ap")
                if not any(item.startswith("mdt-") or item == "client-mac-stored" for item in failed):
                    print("MDT aggregate exported without per-client series")

    tcp.close()
    server.shutdown()
    print("FAILED", failed)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
