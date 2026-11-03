"""9800 MDT catalog, AireOS SNMP counts, and the paste-only controller config."""

from __future__ import annotations

import importlib.util
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "config-api"))

from ie_config.experience import telemetry_config  # noqa: E402
from ie_config.fleet import attach_netbox_sites, events_from_range  # noqa: E402


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _catalog():
    return _load(ROOT / "config" / "telegraf" / "wlc" / "catalog.py", "wlc_catalog_full")


def _render():
    return _load(ROOT / "config" / "telegraf" / "wlc" / "render_wlc.py", "render_wlc_full")


def test_mdt_paths_match_the_listener_and_the_doc():
    catalog = _catalog()
    conf = (ROOT / "config" / "telegraf" / "wlc" / "mdt.conf").read_text()
    doc = (ROOT / "docs" / "wlc-9800-full.md").read_text()
    aliases = catalog.mdt_aliases()
    assert len(aliases) == len({key for key, _path in aliases})
    for _alias, path in aliases:
        assert '"' + path + '"' in conf
        assert path.split(":", 1)[1] in doc or path in doc
    for _offset, xpath, _alias, _policy, _seconds, _shows in catalog.MDT_SUBS:
        assert xpath in doc
    assert "bsnMobileStation" in doc
    assert "IE_WLC_STORE_CLIENTS=0" in doc
    samples = catalog.sample_kvgpb()
    assert len(samples) == len(aliases)


def test_9800_paste_has_every_subscription_and_no_secret():
    os.environ["SNMP_V3_AUTH_PASSWORD"] = "super-secret-auth"
    os.environ["SNMP_V3_PRIV_PASSWORD"] = "super-secret-priv"
    os.environ["SNMP_V3_USERNAME"] = "ie-collector"
    try:
        body = telemetry_config(
            {"name": "wlc-9800", "ip": "10.9.0.8", "role": "wireless-controller", "platform": "ios-xe"},
            receiver="10.1.1.50",
        )
    finally:
        os.environ.pop("SNMP_V3_AUTH_PASSWORD", None)
        os.environ.pop("SNMP_V3_PRIV_PASSWORD", None)
        os.environ.pop("SNMP_V3_USERNAME", None)
        os.environ.pop("SNMP_V2_COMMUNITY", None)
    assert body["configured"] is True
    assert body["pushed"] is False
    assert body["title"] == "Controller config"
    text = body["config"]
    assert "netconf-yang" in text
    assert "source-vrf <VRF>" in text
    assert "encode-kvgpb" in text
    assert "protocol grpc-tcp" in text
    assert "show telemetry ietf subscription all" in text
    assert "show telemetry connection all" in text
    assert "show telemetry internal connection" in text
    assert "ie-collector" in text
    assert "super-secret-auth" not in text
    assert "super-secret-priv" not in text
    assert "<auth-passphrase>" in text
    catalog = _catalog()
    for _offset, xpath, _alias, policy, seconds, _shows in catalog.MDT_SUBS:
        assert xpath in text
        if policy == "on-change":
            assert "update-policy on-change" in text
        else:
            assert "update-policy periodic %d" % (seconds * 100) in text
    assert "wireless-wlan-cfg" in text
    assert "/wireless-rogue-oper:rogue-oper-data/rogue-data" not in text


def test_aireos_render_has_no_client_table():
    text = _render().render(
        [{
            "targets": ["10.1.1.8"],
            "labels": {
                "__meta_netbox_name": "wlc-a",
                "__meta_netbox_platform": "aireos",
                "__meta_netbox_role": "wireless-controller",
                "__meta_netbox_site_name": "rotterdam",
                "__meta_netbox_snmp_auth": "ie_wlc_v2",
            },
        }],
        {"SNMP_V2_COMMUNITY": "public", "IE_WLC_TABLE": "stations"},
    )
    assert "bsnMobile" not in text
    assert "1.3.6.1.4.1.14179.2.1.4" not in text
    assert "not collected" in text


def test_series_estimate_for_the_large_controller():
    est = _catalog().estimate_series(aps=5000, clients_per_ap=15, store_clients=True)
    assert est["per_client_series"] == 5000 * 15 * 8
    assert est["series"] > est["per_client_series"]
    assert est["mdt_megabits_per_sec"] > 1
    quiet = _catalog().estimate_series(aps=5000, store_clients=False)
    assert quiet["per_client_series"] == 0
    assert quiet["series"] < est["series"]


def test_exporter_scalars_are_counts_not_client_rows():
    document = yaml.safe_load((ROOT / "snmp" / "out" / "snmp.yml").read_text())
    iosxe = {metric["name"]: metric["oid"] for metric in document["modules"]["cisco_wlc_iosxe"]["metrics"]}
    aire = {metric["name"]: metric["oid"] for metric in document["modules"]["cisco_wlc_aireos"]["metrics"]}
    assert iosxe["cLMobilityExtMCTotalClientCount"] == "1.3.6.1.4.1.9.9.846.1.1.4.13"
    assert iosxe["cRFStatusUnitState"] == "1.3.6.1.4.1.9.9.176.1.1.2"
    assert aire["bsnGlobalDot11SystemMobileStations"] == "1.3.6.1.4.1.14179.2.3.5.1.1"
    assert aire["cRFStatusPeerUnitState"] == "1.3.6.1.4.1.9.9.176.1.1.4"
    assert aire["agentApAssociateDisassociateTrapCount"] == "1.3.6.1.4.1.14179.1.1.2.6"
    blob = "\n".join(iosxe.values()) + "\n" + "\n".join(aire.values())
    assert "1.3.6.1.4.1.14179.2.1.4" not in blob
    assert "1.3.6.1.4.1.14179.2.1.6" not in blob


def test_snmprec_fixture_is_sorted_and_has_no_client_rows():
    text = _catalog().snmprec_fixture()
    assert _catalog().contains_client_walk(text) is False
    oids = [line.split("|", 1)[0] for line in text.splitlines() if line]
    assert oids == sorted(oids, key=lambda oid: tuple(int(part) for part in oid.split(".")))
    assert "1.3.6.1.4.1.14179.2.3.5.1.1.0" in text
    assert "1.3.6.1.4.1.9.9.513.1.3.35.0" in text


def test_netbox_site_matches_ap_name_then_cdp_switch():
    rows = [
        {"name": "ap-1", "site": "wlc-site", "neighborSwitch": "sw-edge"},
        {"name": "ap-2", "site": "wlc-site", "neighborSwitch": "sw-other"},
    ]
    devices = [
        {"name": "ap-1", "site_name": "Site A"},
        {"name": "sw-other", "site_name": "Site B"},
    ]
    attach_netbox_sites(rows, devices)
    assert rows[0]["netboxSite"] == "Site A"
    assert rows[0]["site"] == "Site A"
    assert rows[1]["netboxSite"] == "Site B"


def test_events_are_step_changes():
    result = [{"metric": {"ap": "ap-1", "radio": "0"}, "values": [[100, "36"], [160, "36"], [220, "40"]]}]
    events = events_from_range(result, "channel")
    assert events == [{"t": 220, "what": "channel", "ap": "ap-1", "radio": "0", "from": "36", "to": "40"}]


def test_promtool_accepts_experience_rules():
    binary = shutil.which("promtool")
    if not binary:
        return
    proc = subprocess.run([binary, "check", "rules", str(ROOT / "config" / "prometheus" / "experience-rules.yml")], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_snmpsim_walks_counts_when_installed(tmp_path):
    sim = shutil.which("snmpsim-command-responder") or os.path.expanduser("~/.local/bin/snmpsim-command-responder")
    if not os.path.isfile(sim):
        return
    data = tmp_path / "data"
    data.mkdir()
    (data / "public.snmprec").write_text(_catalog().snmprec_fixture(), encoding="utf-8")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    proc = subprocess.Popen(
        [sim, "--data-dir=%s" % data, "--agent-udpv4-endpoint=127.0.0.1:%s" % port, "--logging-method=null"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 12
        seen = ""
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            walk = subprocess.run(
                ["snmpwalk", "-v2c", "-c", "public", "-On", "127.0.0.1:%s" % port, "1.3.6.1.4.1.14179.2.3.5.1.1"],
                capture_output=True, text=True,
            )
            if walk.returncode == 0 and "14179.2.3.5.1.1" in walk.stdout:
                seen = walk.stdout
                break
            time.sleep(0.3)
        if shutil.which("snmpwalk"):
            assert "14179.2.3.5.1.1" in seen
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
