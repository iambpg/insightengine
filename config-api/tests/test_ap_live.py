"""Live access-point lookup. SSH is a fake runner; no controller is contacted."""

from __future__ import annotations

import importlib.util
import json
import logging
import threading
import time
from contextlib import nullcontext
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from ie_config.ap_live import (
    LiveLookup,
    SshGate,
    classify_key,
    output_missing,
    parse_aireos_ap_summary,
    parse_aireos_config_general,
    parse_cdp_neighbors,
    parse_iosxe_ap_summary,
    parse_iosxe_config_general,
    platform_kind,
    resolve_owner_wlc,
    validate_ap_name,
)
from ie_config.app import create_app
from ie_config.db import AuditRow
from ie_config.device_cli import PLATFORMS, aireos_login_phase, platform_for, save_credentials
from ie_config.errors import ApiError
from ie_config.fleet import FleetService, _Cache
from ie_config.settings import Settings

ROOT = Path(__file__).parent / "fixtures" / "ap_live"
IOSXE = (ROOT / "iosxe_config_general.txt").read_text(encoding="utf-8")
IOSXE_SUMMARY = (ROOT / "iosxe_ap_summary.txt").read_text(encoding="utf-8")
IOSXE_MISS = (ROOT / "iosxe_not_found.txt").read_text(encoding="utf-8")
AIREOS = (ROOT / "aireos_config_general.txt").read_text(encoding="utf-8")
AIREOS_SUMMARY = (ROOT / "aireos_ap_summary.txt").read_text(encoding="utf-8")
AIREOS_MISS = (ROOT / "aireos_not_found.txt").read_text(encoding="utf-8")
AIREOS_LOGIN = (ROOT / "aireos_login.txt").read_text(encoding="utf-8")
CLI_SECRET = "device-cli-secret"
VAULT_SECRET = "vault-login-secret"


def test_platform_kind_matches_the_wlc_renderer():
    path = Path(__file__).resolve().parents[2] / "config" / "telegraf" / "wlc" / "render_wlc.py"
    spec = importlib.util.spec_from_file_location("render_wlc_live", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    samples = [
        ("IOS-XE", "Wireless controller", "C9800-40"),
        ("iosxe", "", ""),
        ("AireOS", "Wireless controller", "AIR-CT5520"),
        ("Cisco Controller", "", ""),
        ("", "", ""),
    ]
    for sample in samples:
        assert platform_kind(*sample) == module.platform_kind(*sample)


def test_aireos_platform_does_not_steal_ios_switches():
    assert platform_for("AireOS", "Cisco") == "aireos"
    assert platform_for("Cisco Controller", "Cisco") == "aireos"
    assert platform_for("AIR-CT5520", "Cisco") == "aireos"
    assert platform_for("IOS-XE 17.9", "Cisco") == "ios"
    assert platform_for("IOS 15.2", "Cisco") == "ios"
    assert platform_for("Catalyst 9300", "Cisco") == "ios"
    assert PLATFORMS["aireos"]["prep"] == ("config paging disable",)
    assert PLATFORMS["ios"]["prep"] == ("terminal length 0",)


def test_ap_name_validation():
    assert validate_ap_name("AP-LOBBY-12") == "AP-LOBBY-12"
    assert validate_ap_name("ap.floor_2:radio") == "ap.floor_2:radio"
    for bad in ("", "ap name", "ap|name", "show;version", "a" * 65, "-hidden", "ap/name", "ap name\n"):
        with pytest.raises(ApiError) as caught:
            classify_key(bad)
        assert caught.value.status == 400
        assert caught.value.code == "bad_ap_name"
    assert classify_key("00:a2:89:10:11:44") == ("mac", "00:a2:89:10:11:44")
    assert classify_key("10.20.30.44") == ("ip", "10.20.30.44")
    assert classify_key("AP-LOBBY-12") == ("name", "AP-LOBBY-12")


def test_iosxe_config_general_fixture():
    parsed = parse_iosxe_config_general(IOSXE)
    assert parsed["name"] == "AP-LOBBY-12"
    assert parsed["mac"] == "00:a2:89:10:11:44"
    assert parsed["ip"] == "10.20.30.44"
    assert parsed["model"] == "C9120AXI-E"
    assert parsed["serial"] == "FGL2345AB12"
    assert parsed["ios"] == "17.9.4.27"
    assert parsed["mode"] == "Local"
    assert parsed["adminState"] == "Enabled"
    assert parsed["operState"] == "Registered"
    assert parsed["uptime"] == "3 days 4 hours 12 minutes 8 seconds"
    assert parsed["joinTime"] == "11/18/2026 08:14:02"
    assert parsed["location"] == "Floor 2"
    assert parsed["country"] == "ZA"
    assert parsed["primaryController"] == "wlc-rot-01"
    assert parsed["secondaryController"] == "wlc-rot-02"
    assert parsed["siteTag"] == "site-rotterdam"
    assert parsed["policyTag"] == "policy-corp"
    assert parsed["rfTag"] == "rf-default"
    assert parsed["power"] == "PoE/Full Power"
    assert parsed["apGroup"] is None
    radios = {row["slot"]: row for row in parsed["radios"]}
    assert radios["0"]["channel"] == "6"
    assert radios["0"]["admin"] == "Enabled"
    assert radios["0"]["oper"] == "Up"
    assert "15 dBm" in radios["0"]["txPower"]
    assert radios["1"]["channel"] == "36"
    assert "17 dBm" in radios["1"]["txPower"]
    assert output_missing(IOSXE_MISS, "AP-LOBBY-12")
    assert parse_iosxe_config_general("not a table\n!!!")["name"] is None


def test_aireos_config_general_fixture():
    parsed = parse_aireos_config_general(AIREOS)
    assert parsed["name"] == "AP-CAFE-3"
    assert parsed["mac"] == "00:b4:c1:20:30:40"
    assert parsed["ip"] == "10.20.30.45"
    assert parsed["model"] == "AIR-AP2802I-E-K9"
    assert parsed["serial"] == "FGL998877665"
    assert parsed["ios"] == "8.10.190.0"
    assert parsed["mode"] == "FlexConnect"
    assert parsed["adminState"] == "ADMIN_ENABLED"
    assert parsed["operState"] == "REGISTERED"
    assert parsed["uptime"] == "2 days, 03 h 11 m 04 s"
    assert parsed["location"] == "Cafe"
    assert parsed["country"] == "ZA"
    assert parsed["primaryController"] == "wlc-aireos-01"
    assert parsed["secondaryController"] == "wlc-aireos-02"
    assert parsed["apGroup"] == "default-group"
    assert parsed["flexGroup"] == "flex-rot"
    assert parsed["power"] == "PoE/Full Power"
    assert parsed["siteTag"] is None
    radios = {row["slot"]: row for row in parsed["radios"]}
    assert radios["0"]["channel"] == "1"
    assert "17 dBm" in radios["0"]["txPower"]
    assert radios["1"]["channel"] == "44"
    assert output_missing(AIREOS_MISS, "AP-CAFE-3")
    assert output_missing("", "AP-CAFE-3")


def test_summary_fixtures_and_login_transcript():
    ios = parse_iosxe_ap_summary(IOSXE_SUMMARY)
    assert [row["name"] for row in ios] == ["AP-LOBBY-12", "AP-CAFE-3"]
    assert ios[0]["mac"] == "00:a2:89:10:11:44"
    assert ios[0]["ip"] == "10.20.30.44"
    assert ios[0]["model"] == "C9120AXI-E"
    assert ios[0]["operState"] == "Registered"
    assert ios[0]["country"] == "ZA"
    aire = parse_aireos_ap_summary(AIREOS_SUMMARY)
    assert [row["name"] for row in aire] == ["AP-CAFE-3", "AP-LOBBY-12"]
    assert aire[0]["mac"] == "00:b4:c1:20:30:40"
    assert aire[0]["model"] == "AIR-AP2802I-E-K9"
    assert aire[1]["location"] == "Floor 2"
    assert parse_iosxe_ap_summary("") == []
    assert parse_aireos_ap_summary("no header here") == []
    assert aireos_login_phase("(Cisco Controller)\n") == "wait"
    assert aireos_login_phase(AIREOS_LOGIN.split("Password:")[0]) == "username"
    assert aireos_login_phase(AIREOS_LOGIN.split("(Cisco Controller) >")[0]) == "password"
    assert aireos_login_phase(AIREOS_LOGIN) == "ready"
    neighbour = parse_cdp_neighbors("Neighbor Name : sw-rot-01\nNeighbor Port : GigabitEthernet1/0/14\n")
    assert neighbour == {"cdpSwitch": "sw-rot-01", "cdpPort": "GigabitEthernet1/0/14"}


def _device(device_id, name, ip, platform, model, role_slug, site_id, role_name="Wireless controller", custom=None):
    return {
        "id": device_id,
        "name": name,
        "ip": ip,
        "platform": platform,
        "model": model,
        "role_slug": role_slug,
        "role_name": role_name,
        "site_id": site_id,
        "site_name": site_id,
        "custom_fields": custom or {},
        "serial": "",
    }


def _controllers():
    return [
        _device("1", "wlc-rot-01", "10.20.1.10", "IOS-XE", "C9800-40", "wireless-controller", "rot"),
        _device("2", "wlc-aireos-01", "10.20.1.20", "AireOS", "AIR-CT5520", "wlc", "ams"),
        _device("3", "wlc-other", "10.20.1.30", "Cisco Controller", "AIR-CT3504", "wireless-controller", "rot"),
        _device("9", "AP-LOBBY-12", "10.20.30.44", "", "C9120AXI-E", "access_points", "rot", "Access point", {"wlc": "wlc-other"}),
        _device("8", "sw-rot-01", "10.20.9.1", "IOS-XE", "C9300-48P", "access-switch", "rot", "Access switch"),
    ]


def test_owner_resolution_order():
    devices = _controllers()
    suffixes = [".pnp.co.za"]
    metrics = resolve_owner_wlc(
        "AP-LOBBY-12",
        rows=[{"name": "AP-LOBBY-12.pnp.co.za", "mac": "00:a2:89:10:11:44", "wlc": "wlc-rot-01.pnp.co.za"}],
        devices=devices,
        suffixes=suffixes,
    )
    assert metrics[0]["id"] == "1"
    assert metrics[0]["source"] == "metrics"
    assert metrics[0]["platform"] == "iosxe"
    assert all(row["id"] != "8" for row in metrics)
    assert all(row["id"] != "9" for row in metrics)

    by_ip = resolve_owner_wlc(
        "00:a2:89:10:11:44",
        rows=[{"name": "AP-LOBBY-12", "mac": "00:a2:89:10:11:44", "source": "10.20.1.20"}],
        devices=devices,
        suffixes=suffixes,
    )
    assert by_ip[0]["id"] == "2"
    assert by_ip[0]["platform"] == "aireos"
    assert by_ip[0]["source"] == "metrics"

    netbox = resolve_owner_wlc("AP-LOBBY-12", rows=[], devices=devices, suffixes=suffixes)
    assert netbox[0]["id"] == "3"
    assert netbox[0]["source"] == "netbox"
    assert [row["id"] for row in netbox if row["source"] == "search"] == ["2"]

    bare = [row for row in devices if row["id"] != "9"]
    searched = resolve_owner_wlc("AP-UNKNOWN", rows=[], devices=bare, suffixes=suffixes)
    assert [row["id"] for row in searched] == ["2", "3", "1"]
    assert searched[0]["source"] == "search"
    on_site = _device("9", "AP-HALL-1", "10.20.30.50", "", "C9120AXI-E", "access_points", "rot", "Access point")
    site_first = resolve_owner_wlc("AP-HALL-1", rows=[], devices=bare + [on_site], suffixes=suffixes)
    assert [row["id"] for row in site_first] == ["1", "3", "2"]
    assert site_first[0]["source"] == "netbox"

    hinted = resolve_owner_wlc(
        "AP-LOBBY-12",
        rows=[{"name": "AP-LOBBY-12", "wlc": "wlc-rot-01"}],
        devices=devices,
        suffixes=suffixes,
        hint="10.20.1.20",
        last_id="3",
    )
    assert hinted[0]["id"] == "2"


class FakeFleet:
    def __init__(self, settings, devices, rows=None, suffixes=None):
        self.settings = settings
        self.cache = _Cache(60)
        self.devices = devices
        self.rows = list(rows or [])
        self.suffixes = list(suffixes or [".pnp.co.za"])

    def _find_ap(self, key):
        from ie_config.ap_live import _row_matches
        for row in self.rows:
            if _row_matches(row, key, self.suffixes):
                return row
        return None

    def _session(self):
        return nullcontext(None)

    def _devices_raw(self, client):
        return self.devices

    def _suffixes(self):
        return self.suffixes


class Runner:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []
        self.hold = threading.Event()
        self.hold.set()
        self.entered = threading.Event()

    def run(self, host, username, password, prep, command, timeout, aireos_login=False, limit=None):
        self.calls.append({
            "host": host,
            "username": username,
            "password": password,
            "prep": tuple(prep),
            "command": command,
            "aireos": aireos_login,
            "limit": limit,
        })
        self.entered.set()
        assert self.hold.wait(3)
        return self.reply(host, command)


def _cfg(tmp_path: Path):
    class Cfg:
        config_root = str(tmp_path)
        device_cli_secret_dir = str(tmp_path / "device-cli")
    return Cfg()


def _save_cli(settings, device_id, username, password):
    save_credentials(settings, device_id, username, password)


def _grab_logs():
    grabbed = []

    class Grab(logging.Handler):
        def emit(self, record):
            grabbed.append(record.getMessage())

    handler = Grab()
    logger = logging.getLogger()
    logger.addHandler(handler)
    return grabbed, handler, logger


def _ios_reply(host, command):
    if command == "show ap summary":
        return IOSXE_SUMMARY
    if "cdp" in command:
        return "Neighbor Name : sw-rot-01\nNeighbor Port : GigabitEthernet1/0/14\n"
    if host.endswith(".1"):
        return IOSXE_MISS
    return IOSXE


def test_fallback_stops_at_the_first_hit_and_caches(tmp_path):
    devices = [
        _device("1", "wlc-a", "10.0.0.1", "IOS-XE", "C9800-40", "wireless-controller", "rot"),
        _device("2", "wlc-b", "10.0.0.2", "IOS-XE", "C9800-40", "wireless-controller", "rot"),
        _device("3", "wlc-c", "10.0.0.3", "IOS-XE", "C9800-40", "wireless-controller", "rot"),
    ]
    settings = _cfg(tmp_path)
    for device in devices:
        _save_cli(settings, device["id"], "cli-user", CLI_SECRET)
    fleet = FakeFleet(settings, devices)
    runner = Runner(_ios_reply)
    grabbed, handler, logger = _grab_logs()
    try:
        body = LiveLookup(fleet, runner, gate=SshGate(0.2), inflight={}).fetch("AP-LOBBY-12", include_raw=True)
    finally:
        logger.removeHandler(handler)
    assert body["accessPoint"]["name"] == "AP-LOBBY-12"
    assert body["wlc"]["name"] == "wlc-b"
    assert body["resolvedBy"] == "search"
    assert body["cached"] is False
    assert body["accessPoint"]["cdpSwitch"] == "sw-rot-01"
    hosts = [call["host"] for call in runner.calls]
    assert hosts[0] == "10.0.0.1"
    assert "10.0.0.3" not in hosts
    assert all("|" not in call["command"] for call in runner.calls)
    assert any(call["command"] == "show ap name AP-LOBBY-12 config general" for call in runner.calls)
    assert CLI_SECRET not in json.dumps(body)
    assert all(CLI_SECRET not in line for line in grabbed)
    again = LiveLookup(fleet, runner, gate=SshGate(0.2), inflight={}).fetch("AP-LOBBY-12")
    assert again["cached"] is True
    assert len(runner.calls) == len(hosts)
    fresh = LiveLookup(fleet, runner, gate=SshGate(0.2), inflight={}).fetch("AP-LOBBY-12", refresh=True)
    assert fresh["cached"] is False
    assert len(runner.calls) > len(hosts)


def test_mac_summary_and_credential_order(tmp_path):
    device = _device("2", "wlc-aireos-01", "10.20.1.20", "AireOS", "AIR-CT5520", "wlc", "ams")
    settings = _cfg(tmp_path)
    vault = tmp_path / "data" / "vault"
    vault.mkdir(parents=True)
    (vault / "device-logins.json").write_text(json.dumps({
        "accounts": [{"id": "acct-1", "label": "ops", "username": "vault-user", "password": VAULT_SECRET}],
        "worked": {"wlc-aireos-01": "acct-1"},
    }), encoding="utf-8")
    fleet = FakeFleet(settings, [device])

    def reply(host, command):
        if command == "show ap summary":
            return AIREOS_SUMMARY
        if "cdp" in command:
            return "Neighbor Name : sw-cafe-1\nNeighbor Port : GigabitEthernet1/0/4\n" + VAULT_SECRET
        return AIREOS + "\n" + VAULT_SECRET

    runner = Runner(reply)
    body = LiveLookup(fleet, runner, gate=SshGate(0.2), inflight={}).fetch("00:b4:c1:20:30:40", include_raw=True)
    assert runner.calls[0]["username"] == "vault-user"
    assert runner.calls[0]["password"] == VAULT_SECRET
    assert runner.calls[0]["aireos"] is True
    assert runner.calls[0]["prep"] == ("config paging disable",)
    assert runner.calls[0]["command"] == "show ap summary"
    assert any(call["command"] == "show ap config general AP-CAFE-3" for call in runner.calls)
    assert VAULT_SECRET not in json.dumps(body)
    assert body["accessPoint"]["name"] == "AP-CAFE-3"
    assert body["wlc"]["platform"] == "aireos"

    _save_cli(settings, "2", "cli-user", CLI_SECRET)
    fleet.cache.drop_prefix("ap-live")
    runner.calls.clear()

    def reply_cli(host, command):
        if "cdp" in command:
            return "Neighbor Name : sw-cafe-1\nNeighbor Port : GigabitEthernet1/0/4\n" + CLI_SECRET
        return AIREOS + "\n" + CLI_SECRET

    runner.reply = reply_cli
    grabbed, handler, logger = _grab_logs()
    try:
        preferred = LiveLookup(fleet, runner, gate=SshGate(0.2), inflight={}).fetch("AP-CAFE-3", include_raw=True)
    finally:
        logger.removeHandler(handler)
    assert runner.calls[0]["username"] == "cli-user"
    assert runner.calls[0]["password"] == CLI_SECRET
    blob = json.dumps(preferred) + "\n" + "\n".join(grabbed)
    assert CLI_SECRET not in blob
    assert VAULT_SECRET not in blob


def test_each_error_code(tmp_path):
    settings = _cfg(tmp_path)
    aire = _device("2", "wlc-aireos-01", "10.20.1.20", "AireOS", "AIR-CT5520", "wlc", "ams")
    ios = _device("1", "wlc-rot-01", "10.20.1.10", "IOS-XE", "C9800-40", "wireless-controller", "rot")
    no_ip = _device("4", "wlc-noip", "", "IOS-XE", "C9800-40", "wireless-controller", "rot")

    missing = LiveLookup(FakeFleet(settings, [ios]), Runner(_ios_reply), gate=SshGate(0.2), inflight={})
    with pytest.raises(ApiError) as creds:
        missing.fetch("AP-LOBBY-12")
    assert creds.value.status == 409
    assert creds.value.code == "no_ssh_credentials"
    assert creds.value.details["wlc"]["id"] == "1"
    assert "Device CLI" in creds.value.message
    assert CLI_SECRET not in creds.value.message

    _save_cli(settings, "4", "cli-user", CLI_SECRET)
    no_address = LiveLookup(FakeFleet(settings, [no_ip]), Runner(_ios_reply), gate=SshGate(0.2), inflight={})
    with pytest.raises(ApiError) as address:
        no_address.fetch("AP-LOBBY-12")
    assert address.value.code == "no_management_ip"
    assert address.value.status == 409

    def boom(host, command):
        raise ApiError(502, "ssh_failed", "timeout " + CLI_SECRET)

    _save_cli(settings, "1", "cli-user", CLI_SECRET)
    down = LiveLookup(FakeFleet(settings, [ios]), Runner(boom), gate=SshGate(0.2), inflight={})
    with pytest.raises(ApiError) as unreachable:
        down.fetch("AP-LOBBY-12")
    assert unreachable.value.status == 502
    assert unreachable.value.code == "wlc_unreachable"
    assert CLI_SECRET not in unreachable.value.message
    assert CLI_SECRET not in json.dumps(unreachable.value.details)

    def denied(host, command):
        raise ApiError(502, "wlc_auth_failed", "auth " + CLI_SECRET)

    authed = LiveLookup(FakeFleet(settings, [ios]), Runner(denied), gate=SshGate(0.2), inflight={})
    fleet_auth = authed
    with pytest.raises(ApiError) as auth:
        fleet_auth.fetch("AP-LOBBY-12")
    assert auth.value.code == "wlc_auth_failed"
    assert CLI_SECRET not in auth.value.message

    def miss(host, command):
        return IOSXE_MISS

    one = LiveLookup(FakeFleet(settings, [ios]), Runner(miss), gate=SshGate(0.2), inflight={})
    with pytest.raises(ApiError) as single:
        one.fetch("AP-LOBBY-12")
    assert single.value.status == 404
    assert single.value.code == "ap_not_found_on_wlc"
    calls = len(one.runner.calls)
    with pytest.raises(ApiError):
        one.fetch("AP-LOBBY-12")
    assert len(one.runner.calls) == calls

    _save_cli(settings, "2", "cli-user", CLI_SECRET)
    both = LiveLookup(FakeFleet(settings, [ios, aire]), Runner(miss), gate=SshGate(0.2), inflight={})
    with pytest.raises(ApiError) as none:
        both.fetch("AP-MISSING-1")
    assert none.value.code == "ap_not_found"
    assert "wlc-rot-01" in none.value.message
    assert "wlc-aireos-01" in none.value.message
    assert "Searched 2" in none.value.message


def test_semaphore_limits_and_coalescing(tmp_path):
    settings = _cfg(tmp_path)
    devices = [
        _device(str(index), "wlc-%s" % index, "10.9.0.%s" % index, "IOS-XE", "C9800-40", "wireless-controller", "rot")
        for index in range(1, 6)
    ]
    for device in devices:
        _save_cli(settings, device["id"], "cli-user", CLI_SECRET)
    hold = threading.Event()
    entered = []
    lock = threading.Lock()

    def reply(host, command):
        return IOSXE

    class Blocking(Runner):
        def run(self, host, username, password, prep, command, timeout, aireos_login=False, limit=None):
            self.calls.append(command)
            with lock:
                entered.append(host)
            assert hold.wait(3)
            return IOSXE

    runner = Blocking(reply)
    gate = SshGate(wait_seconds=0.15, global_limit=4)
    lookups = [LiveLookup(FakeFleet(settings, [device]), runner, gate=gate, inflight={}) for device in devices[:4]]
    threads = [threading.Thread(target=lookup.fetch, args=("AP-LOBBY-12",)) for lookup in lookups]
    for thread in threads:
        thread.start()
    deadline = time.time() + 2
    while len(entered) < 4 and time.time() < deadline:
        time.sleep(0.01)
    assert len(entered) == 4
    fifth = LiveLookup(FakeFleet(settings, [devices[4]]), runner, gate=gate, inflight={})
    with pytest.raises(ApiError) as busy:
        fifth.fetch("AP-LOBBY-12")
    assert busy.value.status == 503
    assert busy.value.code == "busy"
    hold.set()
    for thread in threads:
        thread.join(3)

    hold.clear()
    entered.clear()
    shared = {}
    one = LiveLookup(FakeFleet(settings, [devices[0]]), runner, gate=SshGate(0.2), inflight=shared)
    two = LiveLookup(FakeFleet(settings, [devices[0]]), runner, gate=SshGate(0.2), inflight=shared)
    results = []

    def collect(lookup):
        results.append(lookup.fetch("AP-SHARE-1"))

    first = threading.Thread(target=collect, args=(one,))
    first.start()
    deadline = time.time() + 2
    while not entered and time.time() < deadline:
        time.sleep(0.01)
    before = len(runner.calls)
    second = threading.Thread(target=collect, args=(two,))
    second.start()
    time.sleep(0.2)
    assert len(runner.calls) == before
    hold.set()
    first.join(3)
    second.join(3)
    assert len(results) == 2
    assert results[0]["accessPoint"]["name"] == results[1]["accessPoint"]["name"]
    shared_commands = [call for call in runner.calls if "AP-SHARE-1" in call]
    assert shared_commands.count("show ap name AP-SHARE-1 config general") == 1
    assert shared_commands.count("show ap name AP-SHARE-1 cdp neighbors") == 1


def test_last_controller_is_tried_first(tmp_path):
    devices = [
        _device("1", "wlc-a", "10.0.0.1", "IOS-XE", "C9800-40", "wireless-controller", "rot"),
        _device("2", "wlc-b", "10.0.0.2", "IOS-XE", "C9800-40", "wireless-controller", "rot"),
    ]
    settings = _cfg(tmp_path)
    for device in devices:
        _save_cli(settings, device["id"], "cli-user", CLI_SECRET)
    fleet = FakeFleet(settings, devices)
    runner = Runner(_ios_reply)
    lookup = LiveLookup(fleet, runner, gate=SshGate(0.2), inflight={})
    first = lookup.fetch("AP-LOBBY-12")
    assert first["wlc"]["name"] == "wlc-b"
    fleet.cache.drop("ap-live:ap-lobby-12")
    runner.calls.clear()
    second = lookup.fetch("AP-LOBBY-12", refresh=True)
    assert second["wlc"]["name"] == "wlc-b"
    assert [call["host"] for call in runner.calls] == ["10.0.0.2", "10.0.0.2"]


def _settings(tmp_path: Path) -> Settings:
    secret = tmp_path / "netbox.token"
    secret.write_text("netbox-test-token\n", encoding="utf-8")
    (tmp_path / "setup-token").write_text("setup-token-value", encoding="utf-8")
    (tmp_path / "apps.yml").write_text("version: 1\napps: []\n", encoding="utf-8")
    return Settings(
        config_root=str(tmp_path),
        apps_file=str(tmp_path / "apps.yml"),
        database_url="sqlite:///" + str(tmp_path / "ie.db"),
        history_dir=str(tmp_path / "history"),
        cookie_secure=False,
        cookie_name="ie_session",
        setup_token_file=str(tmp_path / "setup-token"),
        client_slug="test",
        public_host="monitor.example.com",
        docker_proxy_url="http://127.0.0.1:9",
        scheduler=False,
        netbox_url="http://netbox.test",
        netbox_token_file=str(secret),
        netdisco_database_url="",
        netdisco_out_dir=str(tmp_path / "nd"),
        mib_dir=str(tmp_path / "mibs"),
        candidate_dir=str(tmp_path / "cand"),
        generator_bin="missing",
        device_cli_secret_dir=str(tmp_path / "device-cli"),
        hostname_strip_suffixes=".pnp.co.za",
    )


def test_unknown_ap_key_returns_a_page(tmp_path, monkeypatch):
    http = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"results": []})))
    service = FleetService(_settings(tmp_path), client=http)
    service._decorated = lambda client: ([], {}, [])
    service._find_ap = lambda key: None
    seen = {}

    def find(url, key, suffixes):
        seen["key"] = key
        return None

    monkeypatch.setattr("ie_config.fleet.netdisco_find", find)
    body = service.get_device("ap:Lobby-12")
    assert seen["key"] == "Lobby-12"
    assert body["hostname"] == "Lobby-12"
    assert body["id"] == "ap:Lobby-12"
    assert body["faceplate"]["form_factor"] == "ceiling-ap"
    prom = next(row for row in body["sources"] if row["name"] == "prometheus")
    assert prom["ok"] is False
    with pytest.raises(ApiError) as missing:
        service.get_device("missing-switch")
    assert missing.value.status == 404
    assert missing.value.code == "not_found"


def test_find_ap_falls_back_to_a_single_query(tmp_path):
    http = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"results": []})))
    service = FleetService(_settings(tmp_path), client=http)
    service.cache.put("ap-snapshot", {"rows": [{"name": "other", "mac": "", "serial": "", "ip": ""}]}, ttl=60)
    called = {}

    def snap(client, only=""):
        called["only"] = only
        return {"rows": [{"name": "Lobby-12", "mac": "00:11:22:33:44:55", "serial": "FGL1", "ip": "10.1.1.9"}]}

    service._ap_snapshot = snap
    row = service._find_ap("ap:Lobby-12")
    assert called["only"] == "Lobby-12"
    assert row["name"] == "Lobby-12"
    called.clear()
    service._ap_snapshot = lambda client, only="": (_ for _ in ()).throw(AssertionError("should use the cached row"))
    assert service._find_ap("Lobby-12")["ip"] == "10.1.1.9"
    service.cache.put("ap-snapshot", {"rows": [{"name": "In-Cache", "mac": "", "serial": "", "ip": ""}]}, ttl=60)
    assert service._find_ap("In-Cache")["name"] == "In-Cache"


def test_live_route_requires_a_reader_and_hides_the_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("IE_CONFIG_SCHEDULER", "0")
    monkeypatch.setenv("COOKIE_SECURE", "0")
    calls = []

    def fake_run(self, host, username, password, prep, command, timeout, aireos_login=False, limit=None):
        calls.append(command)
        assert password == CLI_SECRET
        if "cdp" in command:
            return "Neighbor Name : sw-rot-01\nNeighbor Port : GigabitEthernet1/0/14\n"
        return IOSXE

    monkeypatch.setattr("ie_config.device_cli.ParamikoRunner.run", fake_run)

    def netbox(request: httpx.Request) -> httpx.Response:
        if "dcim/devices" in request.url.path:
            return httpx.Response(200, json={"count": 1, "next": None, "results": [{
                "id": 7,
                "name": "wlc-rot-01",
                "serial": "",
                "role": {"name": "Wireless controller", "slug": "wireless-controller"},
                "site": {"id": 1, "name": "Rotterdam", "slug": "rotterdam"},
                "device_type": {"model": "C9800-40", "manufacturer": {"name": "Cisco"}},
                "primary_ip4": {"address": "10.20.1.10/32"},
                "platform": {"name": "IOS-XE"},
                "custom_fields": {},
            }]})
        if request.url.host.startswith("netbox"):
            return httpx.Response(200, json={"count": 0, "next": None, "results": []})
        return httpx.Response(200, json={"status": "success", "data": {"result": []}})

    settings = _settings(tmp_path)
    http = httpx.Client(transport=httpx.MockTransport(netbox))
    fleet = FleetService(settings, client=http)
    app = create_app(settings, fleet=fleet)
    client = TestClient(app)
    assert client.get("/api/v1/access-points/live?key=AP-LOBBY-12").status_code == 401
    client.post(
        "/internal/bootstrap-admin",
        headers={"Authorization": "Bearer setup-token-value"},
        json={"email": "admin@example.com", "password": "Adminpass1234"},
    )
    login = client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "Adminpass1234"})
    assert login.status_code == 200, login.text
    bad = client.get("/api/v1/access-points/live?key=ap%20name")
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "bad_ap_name"
    save_credentials(settings, "7", "cli-user", CLI_SECRET)
    ok = client.get("/api/v1/access-points/live?key=AP-LOBBY-12")
    assert ok.status_code == 200, ok.text
    assert ok.json()["accessPoint"]["name"] == "AP-LOBBY-12"
    assert ok.json()["wlc"]["name"] == "wlc-rot-01"
    assert "show ap name AP-LOBBY-12 config general" in calls
    assert all("|" not in command for command in calls)
    assert CLI_SECRET not in ok.text
    with app.state.sf() as db:
        rows = db.query(AuditRow).filter(AuditRow.action == "ap-live").all()
        blob = " ".join((row.detail or "") + (row.result or "") for row in rows)
    assert CLI_SECRET not in blob
    assert any(row.result == "ok" for row in rows)
