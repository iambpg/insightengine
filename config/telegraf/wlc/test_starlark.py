#!/usr/bin/env python3
"""Telegraf 1.38.3 must accept normalize.star, and the image must ship catalog.py.

go.starlark.net in Telegraf 1.38.3 enables recursion, sets, and global
reassignment. It does not enable while loops or top-level control flow.
A while loop aborts agent startup, so the collector never binds the dial-out
port. This test loads the real script with the 1.38.3 binary and rejects a
while loop, so a looser interpreter cannot hide a regression.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WLC = Path(__file__).resolve().parent
TELEGRAF_VERSION = "1.38.3"
TARBALL_SHA256 = {
    "amd64": "3d0f74bff0577ce1eda7423a6d4cbe6a4ac9fae5ee1bb2f2b5550d2435c69e96",
}
DIALECT_MARKERS = (
    "does not support",
    "could not initialize processor",
    "error parsing",
    "invalid configuration",
    "Error running agent",
)


def _arch() -> str:
    machine = os.uname().machine
    return {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(machine, machine)


def _telegraf_bin() -> Path:
    override = os.environ.get("TELEGRAF_BIN")
    if override:
        binary = Path(override)
        if not binary.is_file():
            raise unittest.SkipTest("TELEGRAF_BIN is not a file: %s" % binary)
        return binary
    arch = _arch()
    digest = TARBALL_SHA256.get(arch)
    if not digest:
        raise unittest.SkipTest("no pinned Telegraf %s tarball for %s" % (TELEGRAF_VERSION, arch))
    cache = Path.home() / ".cache" / "insightengine" / ("telegraf-" + TELEGRAF_VERSION) / "telegraf"
    if cache.is_file():
        return cache
    url = "https://dl.influxdata.com/telegraf/releases/telegraf-%s_linux_%s.tar.gz" % (TELEGRAF_VERSION, arch)
    cache.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        blob = Path(tmp) / "telegraf.tar.gz"
        request = urllib.request.Request(url, headers={"User-Agent": "insightengine-telegraf-test/1.0"})
        hasher = hashlib.sha256()
        with urllib.request.urlopen(request, timeout=180) as response, blob.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                hasher.update(chunk)
        got = hasher.hexdigest()
        if got != digest:
            raise AssertionError("telegraf tarball sha256 %s != %s" % (got, digest))
        with tarfile.open(blob, "r:gz") as archive:
            archive.extractall(tmp, filter="data")
        found = next(Path(tmp).rglob("usr/bin/telegraf"))
        shutil.copy2(found, cache)
        cache.chmod(cache.stat().st_mode | stat.S_IEXEC)
    return cache


def _run_telegraf(binary: Path, config: Path, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["CLIENT_SLUG"] = "ci"
    return subprocess.run(
        [str(binary), "--config", str(config), "--test", "--non-strict-env-handling"],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        check=False,
    )


def _code_text(path: Path) -> str:
    kept = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if "#" in line:
            line = line.split("#", 1)[0]
        kept.append(line)
    return "\n".join(kept)


def _service_block(name: str, follower: str) -> str:
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    section = text.split("\n  %s:\n" % name, 1)[1]
    return section.split("\n  %s:\n" % follower, 1)[0]


class CatalogPackagingTests(unittest.TestCase):
    def test_dockerfile_copies_catalog_beside_the_renderer(self) -> None:
        text = (WLC / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("COPY catalog.py /usr/local/bin/catalog.py", text)
        self.assertIn("COPY render_wlc.py /usr/local/bin/render_wlc.py", text)
        self.assertIn("COPY drop-priv.sh /usr/local/bin/drop-priv.sh", text)
        self.assertIn("ENV PYTHONPATH=/usr/local/bin:/etc/telegraf", text)
        self.assertNotIn("USER 10001", text)

    def test_compose_mounts_catalog_and_sets_pythonpath(self) -> None:
        block = _service_block("telegraf-wlc", "telegraf-wlc-clients")
        clients = _service_block("telegraf-wlc-clients", "telegraf-wlc-radio")
        radio = _service_block("telegraf-wlc-radio", "telegraf-host")
        self.assertIn("PYTHONPATH: /usr/local/bin:/etc/telegraf", block)
        self.assertIn("./config/telegraf/wlc:/etc/telegraf:ro", block)
        self.assertIn("./config/telegraf/wlc/catalog.py:/usr/local/bin/catalog.py:ro", block)
        self.assertIn('user: "0:0"', block)
        self.assertIn("IE_TELEGRAF_WLC_MEM: ${IE_TELEGRAF_WLC_MEM:-6g}", block)
        self.assertIn('memory: "${IE_TELEGRAF_WLC_MEM:-6g}"', block)
        self.assertIn("IE_WLC_ROLE: clients", clients)
        self.assertIn("IE_TELEGRAF_WLC_CLIENTS_MEM: ${IE_TELEGRAF_WLC_CLIENTS_MEM:-4g}", clients)
        self.assertIn('memory: "${IE_TELEGRAF_WLC_CLIENTS_MEM:-4g}"', clients)
        self.assertNotIn("PORT_MDT_CLIENTS", clients)
        self.assertNotIn("ports:", clients)
        self.assertIn("IE_WLC_ROLE: radio", radio)
        self.assertIn("IE_TELEGRAF_WLC_RADIO_MEM: ${IE_TELEGRAF_WLC_RADIO_MEM:-4g}", radio)
        self.assertIn('cpus: "${IE_TELEGRAF_WLC_RADIO_CPUS:-4}"', radio)
        self.assertIn('cpus: "${IE_TELEGRAF_WLC_CLIENTS_CPUS:-2}"', clients)
        self.assertNotIn("ports:", radio)
        wlc_conf = (WLC / "telegraf.conf").read_text(encoding="utf-8")
        self.assertIn("client_forward.star", wlc_conf)
        self.assertIn("http://${IE_WLC_CLIENTS_FORWARD:-telegraf-wlc-clients:9276}/telegraf", wlc_conf)
        self.assertIn("http://${IE_WLC_RADIO_FORWARD:-telegraf-wlc-radio:9277}/telegraf", wlc_conf)
        self.assertIn("[[outputs.http]]", wlc_conf)
        self.assertIn('timeout = "30s"', wlc_conf)
        self.assertIn('content_encoding = "gzip"', wlc_conf)
        self.assertIn("metric_batch_size = 5000", wlc_conf)
        self.assertIn("metric_buffer_limit = 10000", wlc_conf)
        self.assertIn("metric_buffer_limit = 20000", wlc_conf)
        self.assertIn('alias = "wlc-radio"', wlc_conf)
        self.assertIn('alias = "wlc-clients"', wlc_conf)
        self.assertIn("[[inputs.internal]]", wlc_conf)
        self.assertIn("per_instance = true", wlc_conf)
        self.assertNotIn("metric_buffer_limit = 50000", wlc_conf)
        self.assertIn('namedrop = [', wlc_conf)
        clients_conf = (WLC / "telegraf-clients.conf").read_text(encoding="utf-8")
        self.assertIn("[[inputs.http_listener_v2]]", clients_conf)
        self.assertIn('service_address = "tcp://:9276"', clients_conf)

    def test_entrypoint_puts_both_directories_on_pythonpath(self) -> None:
        text = (WLC / "entrypoint.sh").read_text(encoding="utf-8")
        self.assertIn('PYTHONPATH="/usr/local/bin:/etc/telegraf', text)
        self.assertIn("/usr/local/bin/drop-priv.sh", text)
        self.assertIn("IE_WLC_REFRESH_SECONDS:-300", text)
        self.assertIn("IE_TELEGRAF_WLC_MEM:-6g", text)
        self.assertIn("IE_TELEGRAF_WLC_CLIENTS_MEM:-4g", text)
        self.assertIn("IE_TELEGRAF_WLC_RADIO_MEM:-4g", text)
        self.assertIn("telegraf-radio.conf", text)
        self.assertIn('if [ "$role" != "radio" ]', text)
        self.assertNotIn("mdt-clients.conf", text)
        self.assertIn("GOMEMLIMIT", text)
        self.assertIn("reloaded WLC poller", text)
        self.assertNotIn("--watch-config", text)

    def test_render_imports_catalog_from_the_script_dir_or_an_extra_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script_only = root / "script-only"
            beside = root / "beside"
            extra = root / "extra"
            both_script = root / "both-script"
            both_extra = root / "both-extra"
            for path in (script_only, beside, extra, both_script, both_extra):
                path.mkdir()
            shutil.copy(WLC / "render_wlc.py", script_only / "render_wlc.py")
            shutil.copy(WLC / "render_wlc.py", beside / "render_wlc.py")
            shutil.copy(WLC / "catalog.py", beside / "catalog.py")
            shutil.copy(WLC / "render_wlc.py", both_script / "render_wlc.py")
            shutil.copy(WLC / "catalog.py", both_script / "catalog.py")
            (both_extra / "catalog.py").write_text('MDT_SUBS = "extra"\nAIREOS_TABLES = {}\n', encoding="utf-8")
            (extra / "catalog.py").write_text("MDT_SUBS = []\nAIREOS_TABLES = {}\n", encoding="utf-8")
            shutil.copy(WLC / "render_wlc.py", extra / "render_wlc.py")

            missing = self._render(script_only, None)
            self.assertNotEqual(missing.returncode, 0, missing.stderr)
            self.assertIn("ModuleNotFoundError", missing.stderr)

            found = self._render(beside, None)
            self.assertEqual(found.returncode, 0, found.stderr)
            self.assertIn("Generated from NetBox", (beside / "out.conf").read_text(encoding="utf-8"))

            mounted = self._render(extra, extra)
            self.assertEqual(mounted.returncode, 0, mounted.stderr)

            winner = self._which_catalog(both_script, both_extra)
            self.assertTrue(winner.endswith("/both-script/catalog.py"), winner)

    def _render(self, script_dir: Path, catalog_dir: Path | None) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env["IE_NETBOX_SD_URL"] = ""
        env["IE_NETBOX_TOKEN_FILE"] = str(script_dir / "no-token")
        if catalog_dir is None:
            env["IE_WLC_CATALOG_DIR"] = str(script_dir / "missing-catalog-dir")
        else:
            env["IE_WLC_CATALOG_DIR"] = str(catalog_dir)
        return subprocess.run(
            [sys.executable, str(script_dir / "render_wlc.py"), "-o", str(script_dir / "out.conf")],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def _which_catalog(self, script_dir: Path, catalog_dir: Path) -> str:
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env["IE_WLC_CATALOG_DIR"] = str(catalog_dir)
        code = (
            "import importlib.util\n"
            "from pathlib import Path\n"
            "path = Path(%r) / 'render_wlc.py'\n"
            "spec = importlib.util.spec_from_file_location('render_wlc_under_test', path)\n"
            "module = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(module)\n"
            "import catalog\n"
            "print(catalog.__file__)\n"
        ) % str(script_dir)
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout.strip()


class StarlarkDialectTests(unittest.TestCase):
    binary: Path

    @classmethod
    def setUpClass(cls) -> None:
        binary = _telegraf_bin()
        version = subprocess.run(
            [str(binary), "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        if TELEGRAF_VERSION not in (version.stdout + version.stderr):
            raise AssertionError("need Telegraf %s, got %s" % (TELEGRAF_VERSION, version.stdout.strip()))
        cls.binary = binary

    def test_star_files_have_no_while_loops(self) -> None:
        stars = sorted((ROOT / "config" / "telegraf").rglob("*.star"))
        self.assertTrue(stars)
        for path in stars:
            code = _code_text(path)
            self.assertNotRegex(code, r"\bwhile\b", "%s uses while" % path)

    def test_host_api_and_syslog_have_no_starlark_scripts(self) -> None:
        # The UDP/TCP listener emits one raw line. Starlark in the syslog
        # config parses hostname, severity, and message from that line.
        # Host and API configs stay free of Starlark, and syslog has no .star file.
        for name in ("host", "api"):
            base = ROOT / "config" / "telegraf" / name
            self.assertFalse(list(base.rglob("*.star")), name)
            for conf in base.rglob("*.conf"):
                self.assertNotIn("processors.starlark", conf.read_text(encoding="utf-8"), str(conf))
        syslog = ROOT / "config" / "telegraf" / "syslog"
        self.assertFalse(list(syslog.rglob("*.star")), "syslog")
        confs = sorted(syslog.rglob("*.conf"))
        self.assertEqual([path.name for path in confs], ["telegraf.conf"])
        text = confs[0].read_text(encoding="utf-8")
        self.assertEqual(text.count("[[processors.starlark]]"), 1, str(confs[0]))

    def test_dialect_rejects_while_loops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "while.star"
            script.write_text(
                "def apply(metric):\n    i = 0\n    while i < 1:\n        i = i + 1\n    return metric\n",
                encoding="utf-8",
            )
            config = root / "telegraf.conf"
            config.write_text(
                "\n".join([
                    "[agent]",
                    '  interval = "10s"',
                    "  omit_hostname = true",
                    "[[inputs.internal]]",
                    "  collect_memstats = false",
                    "[[processors.starlark]]",
                    '  script = "%s"' % script,
                    "",
                ]),
                encoding="utf-8",
            )
            proc = _run_telegraf(self.binary, config)
        text = proc.stdout + proc.stderr
        self.assertNotEqual(proc.returncode, 0, text)
        self.assertIn("does not support while loops", text)

    def test_normalize_star_loads_and_splits_the_radio_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample = root / "sample.influx"
            sample.write_text(
                "\n".join([
                    "ie_wlc_radio,index=1.2.3.4.5.6.2,wlc=lab,site=hq noise=10i",
                    "ie_wlc_radio,index=10.20.30.40.50.60.7.99,wlc=lab,site=hq channel=36i",
                    "ie_wlc_radio,index=9.8.7,wlc=lab,site=hq channel=1i",
                    "ie_wlc_client_raw,wlc=lab,site=hq,ap_name=AP-1,ms_mac_address=aabbccddeeff most_recent_rssi=-62i,most_recent_snr=28i",
                    "ie_wlc_rogue_raw,index=aabb,wlc=lab value=1i",
                    'ie_wlc_ap_mdt,wlc=lab,site=hq,path=capwap-data name="AP-1",wtp_mac="00:11:22:33:44:55",device_detail/static_info/ap_models/model="C9120AXI-B",device_detail/static_info/board_data/wtp_serial_num="FGL2417ABC1",device_detail/wtp_version/sw_version="17.15.1.4",wtp_ip="10.8.0.10",ap_location/location="floor-1",ap_mode_data/wtp_mode="local",tag_info/site_tag/site_tag_name="site-a",tag_info/policy_tag_info/policy_tag_name="pol-a",tag_info/rf_tag/rf_tag_name="rf-a",ap_state/ap_operation_state="ewlc-ap-state-registered",cdp_enable=1i,alarms_enable=1i,alarm_hold_time=10i,clear_mode=2i,build="17.9.4",cpu_threshold=80i,dart_is_connected=1i,ap_lag_enabled=1i,ap_keepalive_state=3i,action_ap_reload=0i,ctrl_dtls_decrypt_err=3i,ctrl_dtls_failure_type="timeout",ctrl_dtls_setup_req=4i,data_dtls_failure=1i',
                    'ie_wlc_radio_mdt,wlc=lab,site=hq,path=radio-oper-data wtp_mac="00:11:22:33:44:55",radio_slot_id="1",oper_state="run",current_channel=36i',
                    'ie_wlc_client_raw,wlc=lab,site=hq,ap_name=AP-9,ms_mac_address=aabbccddeef0,store_clients=1,ssid=corp,band=5 current_rate="72.2",speed=144i,most_recent_rssi=-60i,most_recent_snr=30i,policy_errs=2i,vlan_name="user vlan",mobility="local",username="alice from floor 2"',
                    'ie_wlc_client_raw,wlc=lab,site=hq,ap_name=AP-3,ms_mac_address=aabbccddeef2,wlc_role=ap,store_clients=1 most_recent_rssi=-55i',
                    'ie_wlc_client_raw,wlc=lab,site=hq,ap_name=AP-8,ms_mac_address=aabbccddeef1,store_clients=0 current_rate="m9",speed=54i,most_recent_rssi=-61i,most_recent_snr=22i',
                    'ie_wlc_rrm,wlc=lab,site=hq,ap_name=AP-7,radio_slot_id=1,path=rrm-measurement current_channel=36i,load/cca_util_percentage=40i,load/rx_noise_channel_utilization=3i,noise/noise/noise_data/0/chan=36i,noise/noise/noise_data/0/noise=-91i,noise/noise/noise_data/1/chan=40i,noise/noise/noise_data/1/noise=-70i,dot11/neighbor/0/rssi=-40i,mystery_counter=5i',
                    'ie_wlc_radio_stats,wlc=lab,site=hq,ap_name=AP-6,radio_slot_id=0,path=radio-oper-stats odd_counter=9i',
                    "",
                ]),
                encoding="utf-8",
            )
            emit = root / "emit.sh"
            emit.write_text("#!/bin/sh\ncat %s\n" % sample, encoding="utf-8")
            emit.chmod(0o755)
            config = root / "telegraf.conf"
            config.write_text(
                "\n".join([
                    "[agent]",
                    '  interval = "10s"',
                    "  omit_hostname = true",
                    "[[inputs.exec]]",
                    '  commands = ["%s"]' % emit,
                    '  data_format = "influx"',
                    '  timeout = "5s"',
                    "[[processors.starlark]]",
                    '  script = "%s"' % (WLC / "normalize.star"),
                    "",
                ]),
                encoding="utf-8",
            )
            proc = _run_telegraf(self.binary, config)
        text = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, text)
        for marker in DIALECT_MARKERS:
            self.assertNotIn(marker, text)
        self.assertIn("ap=1.2.3.4.5.6", text)
        self.assertIn("radio=2,", text)
        self.assertIn("ap=10.20.30.40.50.60", text)
        self.assertIn("radio=7,", text)
        self.assertIn("ap=9.8.7", text)
        self.assertIn("radio=0,", text)
        self.assertIn("ie_wlc_client_radio", text)
        self.assertIn("clients=1", text)
        self.assertIn("ie_wlc_client", text)
        self.assertIn("client=aabbccddeeff", text)
        self.assertIn("ie_wlc_rogue", text)
        self.assertIn("aps=1", text)
        self.assertIn("model=C9120AXI-B", text)
        self.assertIn("sw_version=17.15.1.4", text)
        self.assertIn("serial=FGL2417ABC1", text)
        self.assertIn("location=floor-1", text)
        self.assertIn("site_tag=site-a", text)
        self.assertIn("policy_tag=pol-a", text)
        self.assertIn("rf_tag=rf-a", text)
        self.assertIn("ap_name=AP-1", text)
        self.assertIn("mac=00:11:22:33:44:55", text)
        self.assertIn("oper_up=1", text)
        self.assertIn("current_rate=72.2", text)
        self.assertIn("speed=144", text)
        self.assertIn("policy_errs=2", text)
        self.assertNotIn("client=aabbccddeef1", text)
        self.assertNotIn("client=aabbccddeef2", text)
        client_line = ""
        for raw in text.splitlines():
            line = raw[2:] if raw.startswith("> ") else raw
            if line.startswith("ie_wlc_client,") and "client=aabbccddeef0" in line:
                client_line = line
                break
        self.assertNotEqual(client_line, "", text[-2000:])
        tags = client_line.split(" ", 1)[0]
        for label in ("wlc=lab", "ap=AP-9", "ssid=corp", "band=5", "client=aabbccddeef0"):
            self.assertIn(label, tags)
        for label in ("radio=", "site=", "vlan", "mobility=", "protocol=", "username="):
            self.assertNotIn(label, tags)
        self.assertNotIn("alice from floor", client_line)
        self.assertNotIn("user vlan", client_line)
        self.assertIn("noise=-91", text)
        self.assertIn("noise_36=-91", text)
        self.assertIn("noise_40=-70", text)
        self.assertIn("rx_noise_channel_utilization=3", text)
        self.assertIn("ctrl_dtls_decrypt_err=3", text)
        self.assertIn("data_dtls_failure=1", text)
        self.assertNotIn("cdp_enable", text)
        self.assertNotIn("alarms_enable", text)
        self.assertNotIn("alarm_hold_time", text)
        self.assertNotIn("clear_mode", text)
        self.assertNotIn("17.9.4", text)
        self.assertNotIn("cpu_threshold", text)
        self.assertNotIn("dart_is_connected", text)
        self.assertNotIn("ap_lag_enabled", text)
        self.assertNotIn("ap_keepalive_state", text)
        self.assertNotIn("action_ap_reload", text)
        self.assertNotIn("failure_type", text)
        self.assertNotIn("timeout", text)
        self.assertNotIn("setup_req", text)
        self.assertNotIn("mystery_counter=5", text)
        self.assertNotIn("odd_counter=9", text)
        self.assertNotIn("rssi=-40", text)
        self.assertNotIn("noise=3", text)
        self.assertNotIn("noise=-70", text)

    def test_large_ap_oper_record_keeps_newest_history_only(self) -> None:
        entries = 40
        newest = entries // 2
        history = []
        for index in range(entries):
            stamp = "2026-11-17T21:00:00Z" if index == newest else "2020-01-01T00:00:00Z"
            history.append('ap_state/ewlc-ap-state-ptr/%d/join-time="%s"' % (index, stamp))
            history.append("ap_state/ewlc-ap-state-ptr/%d/uptime=%di" % (index, index))
            history.append(
                'ap_state/ewlc-ap-state-ptr/%d/note="free text join %d happened after a reboot"' % (index, index)
            )
            history.append('ewlc_ap_state_ptr_%d_join_time="%s"' % (index, stamp))
            history.append("ewlc_ap_state_ptr_%d_bytes=%di" % (index, 100 + index))
        ap_fields = ",".join(history + [
            'name="AP-1"',
            'wtp_mac="00:11:22:33:44:55"',
            "mystery_counter=5i",
            "noise/noise/noise_data/0/chan=36i",
            "noise/noise/noise_data/0/noise=-91i",
            "noise/noise/noise_data/1/chan=40i",
            "noise/noise/noise_data/1/noise=-70i",
        ])
        reasons = []
        for index in range(200):
            reasons.append(
                'ie_wlc_ap_mdt,wlc=lab,site=hq,path=capwap-data name="AP-reason-%d",ap_state/ap_operation_state="ewlc-ap-state-registered",reboot_reason="reason-%d"'
                % (index, index)
            )
        sample_text = "\n".join([
            "ie_wlc_ap_mdt,wlc=lab,site=hq,path=capwap-data " + ap_fields,
        ] + reasons + [""])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample = root / "sample.influx"
            sample.write_text(sample_text, encoding="utf-8")
            emit = root / "emit.sh"
            emit.write_text("#!/bin/sh\ncat %s\n" % sample, encoding="utf-8")
            emit.chmod(0o755)
            config = root / "telegraf.conf"
            config.write_text(
                "\n".join([
                    "[agent]",
                    '  interval = "10s"',
                    "  omit_hostname = true",
                    "[[inputs.exec]]",
                    '  commands = ["%s"]' % emit,
                    '  data_format = "influx"',
                    '  timeout = "20s"',
                    "[[processors.starlark]]",
                    '  script = "%s"' % (WLC / "normalize.star"),
                    "",
                ]),
                encoding="utf-8",
            )
            proc = _run_telegraf(self.binary, config, timeout=60)
        text = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, text[-4000:])
        ap_line = ""
        for raw in text.splitlines():
            line = raw[2:] if raw.startswith("> ") else raw
            if line.startswith("ie_wlc_ap,") and "ap=AP-1" in line.split(" ", 1)[0]:
                ap_line = line
                break
        self.assertNotEqual(ap_line, "", text[-4000:])
        fields = ap_line.split(" ", 1)[1].split(",")
        self.assertLess(len(fields), 30, ap_line)
        self.assertIn("uptime=%di" % newest, ap_line)
        self.assertIn("bytes=%di" % (100 + newest), ap_line)
        self.assertIn("mystery_counter=5", ap_line)
        self.assertIn("noise=-91", ap_line)
        self.assertIn("noise_36=-91", ap_line)
        self.assertIn("noise_40=-70", ap_line)
        self.assertNotIn("uptime=0i", ap_line)
        self.assertNotIn("uptime=39i", ap_line)
        self.assertNotIn("ewlc_ap_state_ptr_", ap_line)
        metrics = "\n".join(
            (raw[2:] if raw.startswith("> ") else raw)
            for raw in text.splitlines()
            if raw.startswith("> ")
        )
        self.assertNotIn("free text", metrics)
        self.assertNotIn("2020-01-01", metrics)
        self.assertNotIn("2026-11-17", metrics)
        seen = set()
        for raw in text.splitlines():
            line = raw[2:] if raw.startswith("> ") else raw
            marker = "reboot_reason="
            if marker not in line:
                continue
            for part in line.replace(",", " ").split():
                if part.startswith(marker):
                    seen.add(part)
        self.assertEqual(len(seen), 128, sorted(seen)[:5])

    def test_client_rows_are_forwarded_before_normalize(self) -> None:
        sample = "\n".join([
            'ie_wlc_client_raw,wlc=lab,ap_name=AP-9,ms_mac_address=aabbccddeef9,store_clients=1,ssid=corp,band=5,wlc_role=ap most_recent_rssi=-60i,username="alice from floor 2"',
            'ie_wlc_ap_mdt,wlc=lab,site=hq,path=capwap-data name="AP-1",wtp_mac="00:11:22:33:44:55",ap_state/ap_operation_state="ewlc-ap-state-registered"',
            "",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sample.influx").write_text(sample, encoding="utf-8")
            emit = root / "emit.sh"
            emit.write_text("#!/bin/sh\ncat %s\n" % (root / "sample.influx"), encoding="utf-8")
            emit.chmod(0o755)
            (root / "clients.conf").write_text(
                "\n".join([
                    "[agent]",
                    '  interval = "1s"',
                    "  round_interval = false",
                    "  omit_hostname = true",
                    "  quiet = true",
                    "  metric_buffer_limit = 1000",
                    "[[outputs.prometheus_client]]",
                    '  listen = "127.0.0.1:19374"',
                    "  metric_version = 2",
                    '  expiration_interval = "300s"',
                    "  string_as_label = true",
                    "[[inputs.http_listener_v2]]",
                    '  service_address = "tcp://127.0.0.1:19376"',
                    '  paths = ["/telegraf"]',
                    '  data_format = "influx"',
                    "  [inputs.http_listener_v2.tags]",
                    '    wlc_role = "clients"',
                    "[[processors.starlark]]",
                    '  script = "%s"' % (WLC / "normalize.star"),
                    "",
                ]),
                encoding="utf-8",
            )
            (root / "wlc.conf").write_text(
                "\n".join([
                    "[agent]",
                    '  interval = "1s"',
                    "  round_interval = false",
                    "  omit_hostname = true",
                    "  quiet = true",
                    "  metric_batch_size = 100",
                    "  metric_buffer_limit = 1000",
                    '  flush_interval = "1s"',
                    "[[outputs.http]]",
                    '  url = "http://127.0.0.1:19376/telegraf"',
                    '  data_format = "influx"',
                    '  method = "POST"',
                    '  timeout = "5s"',
                    "  metric_batch_size = 100",
                    "  metric_buffer_limit = 50",
                    '  namepass = ["ie_wlc_client_raw"]',
                    "[[outputs.prometheus_client]]",
                    '  listen = "127.0.0.1:19373"',
                    "  metric_version = 2",
                    '  expiration_interval = "1200s"',
                    "  string_as_label = true",
                    '  namedrop = ["ie_wlc_client_raw"]',
                    "[[inputs.exec]]",
                    '  commands = ["%s"]' % emit,
                    '  data_format = "influx"',
                    '  timeout = "10s"',
                    '  interval = "1s"',
                    "[[processors.starlark]]",
                    '  namepass = ["ie_wlc_client_raw"]',
                    '  script = "%s"' % (WLC / "client_forward.star"),
                    "[[processors.starlark]]",
                    '  namedrop = ["ie_wlc_client_raw"]',
                    '  script = "%s"' % (WLC / "normalize.star"),
                    "",
                ]),
                encoding="utf-8",
            )
            env = dict(os.environ)
            env["CLIENT_SLUG"] = "ci"
            clients_err = open(root / "clients.err", "w", encoding="utf-8")
            wlc_err = open(root / "wlc.err", "w", encoding="utf-8")
            clients = subprocess.Popen(
                [str(self.binary), "--config", str(root / "clients.conf"), "--non-strict-env-handling"],
                stdout=subprocess.DEVNULL,
                stderr=clients_err,
                env=env,
            )
            wlc = None
            try:
                time.sleep(1)
                wlc = subprocess.Popen(
                    [str(self.binary), "--config", str(root / "wlc.conf"), "--non-strict-env-handling"],
                    stdout=subprocess.DEVNULL,
                    stderr=wlc_err,
                    env=env,
                )
                ap_body = ""
                client_body = ""
                deadline = time.time() + 25
                while time.time() < deadline:
                    try:
                        ap_body = urllib.request.urlopen("http://127.0.0.1:19373/metrics", timeout=2).read().decode()
                        client_body = urllib.request.urlopen("http://127.0.0.1:19374/metrics", timeout=2).read().decode()
                    except Exception:
                        time.sleep(0.5)
                        continue
                    if "ie_wlc_ap" in ap_body and "ie_wlc_client_rssi" in client_body:
                        break
                    time.sleep(0.5)
            finally:
                for proc in (wlc, clients):
                    if proc is None:
                        continue
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                clients_err.close()
                wlc_err.close()
                if "ie_wlc_ap" not in ap_body or "ie_wlc_client_rssi" not in client_body:
                    sys.stderr.write((root / "wlc.err").read_text(encoding="utf-8")[-2000:])
                    sys.stderr.write((root / "clients.err").read_text(encoding="utf-8")[-2000:])
        self.assertIn("ie_wlc_ap", ap_body)
        self.assertNotIn("aabbccddeef9", ap_body)
        self.assertNotIn("ie_wlc_client_rssi", ap_body)
        self.assertIn("ie_wlc_client_rssi", client_body)
        self.assertIn("aabbccddeef9", client_body)
        self.assertNotIn("alice from floor", client_body)

    def test_host_api_and_syslog_configs_parse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = {
                "api": 19273,
                "host": 19274,
                "syslog": 19275,
            }
            for name, port in cases.items():
                source = ROOT / "config" / "telegraf" / name / "telegraf.conf"
                text = source.read_text(encoding="utf-8")
                text = text.replace('listen = ":9273"', 'listen = ":%d"' % port)
                text = text.replace("udp://:6514", "udp://:%d" % (port + 100))
                text = text.replace("tcp://:6514", "tcp://:%d" % (port + 101))
                dest = root / ("%s.conf" % name)
                dest.write_text(text, encoding="utf-8")
                proc = _run_telegraf(self.binary, dest, timeout=40)
                output = proc.stdout + proc.stderr
                for marker in DIALECT_MARKERS:
                    self.assertNotIn(marker, output, name)
                self.assertEqual(proc.returncode, 0, "%s\n%s" % (name, output[-2000:]))


if __name__ == "__main__":
    unittest.main()
