"""NetBridge matching, plans, EoX, vault credentials, roles, and an in-process WLC walk."""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from ie_config.app import create_app
from ie_config.db import DiscoveryCandidate, make_session_factory
from ie_config.discovery import Discovery
from ie_config.netbridge.ber import decode_message, enc_str, encode_getbulk, encode_response
from ie_config.netbridge.eox import EoxClient, record_fields
from ie_config.netbridge.plan import (
    UnsafeChange,
    accept_geocode,
    eox_bucket,
    paginate,
    plan_addresses,
    plan_stacks,
    round_coord,
    validate_changes,
)
from ie_config.netbridge.match import build_index, match_one
from ie_config.netbridge.service import NetBridge
from ie_config.netbridge.snmp import AIRE_IP, AIRE_MODEL, AIRE_NAME, AIRE_SERIAL, CDP_AP, CDP_NEIGH, CDP_PORT, scan_wlc, value_for, walk
from ie_config.settings import Settings
from ie_config.vault import secret_value


def test_serial_beats_hostname_and_suffix():
    suffixes = [".pnp.co.za"]
    netbox = [
        {"id": 1, "name": "sw1", "serial": "FOC999", "ip": "10.0.0.9"},
        {"id": 2, "name": "sw1", "serial": "FOC111", "ip": "10.0.0.1"},
    ]
    index = build_index(netbox, suffixes)
    found = match_one({"name": "sw1.pnp.co.za", "serial": "FOC111", "ip": "10.9.9.9"}, index, suffixes)
    assert found["via"] == "serial"
    assert found["device"]["id"] == 2
    by_name = match_one({"name": "sw1.pnp.co.za", "serial": "", "ip": ""}, index, suffixes)
    assert by_name["conflict"] == "hostname"
    by_ip = match_one({"name": "", "serial": "", "ip": "10.0.0.9"}, index, suffixes)
    assert by_ip["via"] == "ip" and by_ip["device"]["id"] == 1


def test_stack_plan_never_renames_or_touches_rack():
    devices = [{"ip": "10.1.1.1", "name": "stk1.pnp.co.za", "serial": "MST", "model": "C9300", "vendor": "Cisco"}]
    modules = [
        {"ip": "10.1.1.1", "index": 1, "name": "Switch 1", "class": "stack", "pos": 1, "serial": "SER1", "model": "C9300-48P"},
        {"ip": "10.1.1.1", "index": 2, "name": "Switch 2", "class": "stack", "pos": 2, "serial": "SER2", "model": "C9300-48P"},
    ]
    netbox = [{"id": 8, "name": "stk1", "serial": "SER1", "ip": "10.1.1.1", "site": "Lab", "role": "Access switch", "vc_id": None}]
    planned = plan_stacks(devices, modules, netbox, [".pnp.co.za"])
    validate_changes(planned["changes"])
    assert planned["stacks"][0]["name"] == "stk1"
    ops = [change["op"] for change in planned["changes"]]
    assert "delete" not in ops
    assert "create_vc" in ops
    attach = next(change for change in planned["changes"] if change["op"] == "attach_vc")
    assert set(attach["fields"]) <= {"virtual_chassis", "vc_position"}
    assert "rack" not in json.dumps(planned["changes"])
    created = next(change for change in planned["changes"] if change["op"] == "create_device")
    assert created["serial"] == "SER2"
    assert "rack" not in created


def test_address_plan_skips_a_different_owner():
    addresses = [{"device_ip": "10.0.0.1", "address": "10.0.0.50", "port": "Vlan1", "dns": ""}]
    devices = [{"ip": "10.0.0.1", "name": "sw1", "serial": "AAA"}]
    netbox = [{"id": 3, "name": "sw1", "serial": "AAA", "ip": "10.0.0.1", "primary_set": True}]
    existing = {"10.0.0.50": {"device_id": 9, "device": "other", "interface": "Vlan1"}}
    planned = plan_addresses(addresses, devices, netbox, existing, [])
    assert planned["rows"][0]["action"] == "conflict"
    assert planned["changes"] == []


def test_eox_buckets_and_record_shape():
    today = date(2026, 11, 3)
    assert eox_bucket("2020-01-01", today) == "past"
    assert eox_bucket("2027-01-01", today) == "soon"
    assert eox_bucket("2030-01-01", today) == "ok"
    assert eox_bucket("", today) == "unknown"
    fields = record_fields({
        "EOLProductID": "WS-C2960-24TC-L",
        "EndOfSaleDate": {"value": "2018-10-31"},
        "EndOfSWMaintenanceReleases": {"value": "2019-10-31"},
        "EndOfSecurityVulSupportDate": "2020-10-31",
        "LastDateOfSupport": {"value": "2023-10-31"},
        "MigrationInformation": {"MigrationProductId": "C9200-24P"},
    })
    assert fields["migration_pid"] == "C9200-24P"
    assert fields["end_of_sale"] == "2018-10-31"
    assert round_coord("51.123456789") == 51.123457


def test_geocode_is_bounded_by_country():
    site = {"name": "Cape Town", "region": "Western Cape", "country": "South Africa", "country_code": "za"}
    good = {"lat": "-33.9", "lon": "18.4", "label": "Cape Town, Western Cape, South Africa", "country": "South Africa", "country_code": "za"}
    other = {"lat": "40", "lon": "-74", "label": "Cape Town, United States", "country": "United States", "country_code": "us"}
    assert accept_geocode(site, good)
    assert not accept_geocode(site, other)


def test_eox_client_batches_and_hides_secrets():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url).split("?")[0], request.headers.get("authorization", "")))
        if request.url.path.endswith("/token"):
            assert b"client_secret" in request.content
            return httpx.Response(200, json={"access_token": "secret-token", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer secret-token"
        return httpx.Response(200, json={"EOXRecord": [{
            "EOLProductID": "PID-1",
            "LastDateOfSupport": {"value": "2030-01-01"},
            "EndOfSaleDate": {"value": "2020-01-01"},
            "MigrationInformation": {"MigrationProductId": "PID-2"},
        }, {
            "EOLProductID": "PID-2",
            "LastDateOfSupport": {"value": "2024-01-01"},
        }]})

    client = EoxClient("id-value", "secret-value", http=httpx.Client(transport=httpx.MockTransport(handler)), pause=0)
    found = client.lookup_products(["PID-1", "PID-2"])
    assert found["PID-1"]["migration_pid"] == "PID-2"
    assert found["PID-1"]["bucket"] == "ok"
    probe = client.probe()
    assert probe["ok"] is True
    blob = json.dumps(seen) + json.dumps(probe)
    assert "secret-value" not in blob
    assert "id-value" not in blob
    missing = EoxClient("", "")
    assert missing.probe()["ok"] is False
    assert "Vault" in missing.probe()["message"]


def test_unsafe_change_is_refused_before_any_write():
    try:
        validate_changes([{"op": "delete", "device_id": 1}])
    except UnsafeChange:
        pass
    else:
        raise AssertionError("delete was allowed")
    try:
        validate_changes([{"op": "attach_vc", "fields": {"name": "renamed", "virtual_chassis": 1}}])
    except UnsafeChange:
        pass
    else:
        raise AssertionError("rename was allowed")


def _settings(tmp_path: Path) -> Settings:
    (tmp_path / "secrets").mkdir()
    token = tmp_path / "secrets" / "netbox.token"
    token.write_text("nbt_testtoken\n", encoding="utf-8")
    (tmp_path / "setup-token").write_text("setup-token-value", encoding="utf-8")
    (tmp_path / "apps.yml").write_text("version: 1\napps: []\n", encoding="utf-8")
    (tmp_path / ".env").write_text("PUBLIC_HOST=monitor.example.com\n", encoding="utf-8")
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
        netbox_url="http://127.0.0.1:9",
        netbox_token_file=str(token),
        netdisco_database_url="",
        netdisco_out_dir=str(tmp_path / "nd"),
        mib_dir=str(tmp_path / "mibs"),
        candidate_dir=str(tmp_path / "cand"),
        generator_bin="missing",
        env_file=str(tmp_path / ".env"),
    )


def _client(tmp_path: Path):
    app = create_app(_settings(tmp_path))
    client = TestClient(app)
    created = client.post(
        "/internal/bootstrap-admin",
        headers={"Authorization": "Bearer setup-token-value"},
        json={"email": "admin@example.com", "password": "Adminpass1234"},
    )
    assert created.status_code == 200, created.text
    logged = client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "Adminpass1234"})
    assert logged.status_code == 200, logged.text
    return client, logged.json()["csrfToken"], app


def test_role_choice_is_stored_until_approval(tmp_path):
    client, csrf, app = _client(tmp_path)
    factory, _engine = make_session_factory(app.state.settings.database_url)
    with factory() as db:
        db.add(DiscoveryCandidate(ip="10.9.9.9", name="sw-new.pnp.co.za", status="pending", role_slug="access-switch", site_slug="Lab"))
        db.commit()
        cid = db.scalar(__import__("sqlalchemy").select(DiscoveryCandidate.id))
    saved = client.post(
        "/api/v1/discovery/roles",
        headers={"X-CSRF-Token": csrf},
        json={"ids": [cid], "role": "Core switch"},
    )
    assert saved.status_code == 200, saved.text
    rows = client.get("/api/v1/discovery/unapproved").json()
    assert rows[0]["suggested"]["role"] == "Core switch"
    page = client.get("/api/v1/discovery/unapproved?page=1&page_size=10&q=sw-new").json()
    assert page["total"] == 1
    assert page["rows"][0]["suggested"]["role"] == "Core switch"
    # A later discovery pass must not replace a role the operator chose.
    discovery = Discovery(app.state.settings, factory, str(tmp_path))
    (tmp_path / "nd").mkdir()
    (tmp_path / "nd" / "scan-prefixes.txt").write_text("10.9.9.0/24\n", encoding="utf-8")
    discovery.fetch_netbox_ips = lambda: set()
    discovery.fetch_netdisco_devices = lambda: [{"ip": "10.9.9.9", "name": "sw-new.pnp.co.za", "sysdescr": "Cisco", "vendor": "Cisco", "model": "C9300"}]
    discovery.fetch_prefixes = lambda: []
    discovery.ip_assigned_in_netbox = lambda ip: False
    discovery.refresh_unapproved()
    again = client.get("/api/v1/discovery/unapproved").json()
    assert again[0]["suggested"]["role"] == "Core switch"


def test_preview_does_not_write_until_confirm(tmp_path, monkeypatch):
    client, csrf, app = _client(tmp_path)
    calls = []

    def boom(settings, changes):
        calls.append(changes)
        return {"counts": {"created": 1, "updated": 0, "skipped": 0, "errors": 0}, "errors": []}

    monkeypatch.setattr("ie_config.netbridge.sources.apply_changes", boom)
    bridge = NetBridge(app.state.settings, app.state.sf, app.state.discovery)
    app.state.netbridge = bridge
    bridge.netdisco = lambda: {"ok": True, "message": "", "devices": [], "modules": [], "addresses": []}
    bridge.netbox_devices = lambda: []
    preview = client.post("/api/v1/netbridge/stacks/preview", headers={"X-CSRF-Token": csrf}, json={})
    assert preview.status_code == 200, preview.text
    assert preview.json()["dryRun"] is True
    assert calls == []
    refused = client.post("/api/v1/netbridge/stacks/apply", headers={"X-CSRF-Token": csrf}, json={"previewId": preview.json()["previewId"]})
    assert refused.status_code == 400
    assert calls == []
    applied = client.post(
        "/api/v1/netbridge/stacks/apply",
        headers={"X-CSRF-Token": csrf},
        json={"previewId": preview.json()["previewId"], "confirm": True},
    )
    assert applied.status_code == 200, applied.text
    assert calls == [] or calls == [[]]


def test_conflicts_round_trip_and_open_count(tmp_path):
    client, csrf, app = _client(tmp_path)
    bridge = NetBridge(app.state.settings, app.state.sf, app.state.discovery)
    app.state.netbridge = bridge
    bridge.persist_conflicts([{
        "fingerprint": "serial|foc1|foc2",
        "kind": "serial",
        "left": "FOC1",
        "right": "FOC2",
        "detail": {"note": "kept"},
    }])
    listed = client.get("/api/v1/netbridge/conflicts?page=1&page_size=10&q=FOC").json()
    assert listed["total"] == 1
    assert client.get("/api/v1/netbridge/open-count").json()["open"] == 1
    cid = listed["rows"][0]["id"]
    ignored = client.post("/api/v1/netbridge/conflicts/%s" % cid, headers={"X-CSRF-Token": csrf}, json={"action": "ignore"})
    assert ignored.status_code == 200, ignored.text
    assert client.get("/api/v1/netbridge/open-count").json()["open"] == 0
    # Ignored mismatches stay ignored when the same fingerprint is seen again.
    bridge.persist_conflicts([{
        "fingerprint": "serial|foc1|foc2",
        "kind": "serial",
        "left": "FOC1",
        "right": "FOC2",
        "detail": {},
    }])
    assert client.get("/api/v1/netbridge/conflicts?status=ignored").json()["total"] == 1


def test_vault_integrations_are_masked(tmp_path, caplog):
    client, csrf, app = _client(tmp_path)
    secret = "cisco-secret-value"
    token = "fmg-token-value"
    caplog.set_level(logging.DEBUG)
    saved = client.post(
        "/api/v1/settings/vault/integrations",
        headers={"X-CSRF-Token": csrf},
        json={
            "ciscoClientId": "cisco-client-id",
            "ciscoClientSecret": secret,
            "fortimanagerUrl": "https://fmg.example.com",
            "fortimanagerToken": token,
            "iseUrl": "https://ise.example.com",
            "iseUsername": "iseadmin",
            "isePassword": "IsePass1234",
            "infobloxUrl": "https://gm.example.com",
            "infobloxUsername": "ibadmin",
            "infobloxPassword": "IbloxPass1234",
        },
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["integrations"]["cisco"]["secretSet"] is True
    assert body["integrations"]["fortimanager"]["tokenSet"] is True
    assert body["integrations"]["fortimanager"]["url"] == "https://fmg.example.com"
    assert body["integrations"]["ise"]["url"] == "https://ise.example.com"
    assert body["integrations"]["ise"]["username"] == "iseadmin"
    assert body["integrations"]["ise"]["passwordSet"] is True
    assert body["integrations"]["infoblox"]["url"] == "https://gm.example.com"
    assert body["integrations"]["infoblox"]["username"] == "ibadmin"
    assert body["integrations"]["infoblox"]["passwordSet"] is True
    blob = saved.text + caplog.text
    assert secret not in blob
    assert token not in blob
    assert "IsePass1234" not in blob
    assert "IbloxPass1234" not in blob
    assert "cisco-client-id" not in blob
    listed = client.get("/api/v1/settings/vault")
    assert secret not in listed.text
    assert token not in listed.text
    assert "IsePass1234" not in listed.text
    assert "IbloxPass1234" not in listed.text
    assert listed.json()["integrations"]["infoblox"]["username"] == "ibadmin"
    assert "cisco-client-id" not in listed.text
    assert listed.json()["integrations"]["ise"]["username"] == "iseadmin"
    assert listed.json()["integrations"]["fortimanager"]["url"] == "https://fmg.example.com"
    locked = client.post(
        "/api/v1/settings/vault/reveal",
        headers={"X-CSRF-Token": csrf},
        json={"key": "ISE_PASSWORD", "action": "reveal"},
    )
    assert locked.status_code == 403
    assert locked.json()["error"]["code"] == "reauth_required"
    assert "IsePass1234" not in locked.text
    opened = client.post(
        "/api/v1/settings/vault/unlock",
        headers={"X-CSRF-Token": csrf},
        json={"password": "Adminpass1234"},
    )
    assert opened.status_code == 200, opened.text
    shown = client.post(
        "/api/v1/settings/vault/reveal",
        headers={"X-CSRF-Token": csrf},
        json={"key": "ISE_PASSWORD", "action": "reveal"},
    )
    assert shown.status_code == 200, shown.text
    assert shown.json()["value"] == "IsePass1234"
    iblox = client.post(
        "/api/v1/settings/vault/reveal",
        headers={"X-CSRF-Token": csrf},
        json={"key": "INFOBLOX_PASSWORD", "action": "reveal"},
    )
    assert iblox.status_code == 200, iblox.text
    assert iblox.json()["value"] == "IbloxPass1234"
    assert "IbloxPass1234" not in caplog.text
    token_shown = client.post(
        "/api/v1/settings/vault/reveal",
        headers={"X-CSRF-Token": csrf},
        json={"key": "FORTIMANAGER_TOKEN", "action": "reveal"},
    )
    assert token_shown.status_code == 200, token_shown.text
    assert token_shown.json()["value"] == token
    assert "IsePass1234" not in caplog.text
    assert token not in caplog.text
    revealed = client.post(
        "/api/v1/settings/vault/reveal",
        headers={"X-CSRF-Token": csrf},
        json={"key": "CISCO_API_CLIENT_SECRET", "action": "reveal"},
    )
    assert revealed.status_code == 403
    assert revealed.json()["error"]["code"] == "secret_withheld"
    assert secret not in revealed.text
    assert secret_value(app.state.settings, "CISCO_API_CLIENT_SECRET") == secret
    # A blank save keeps the stored secret.
    again = client.post(
        "/api/v1/settings/vault/integrations",
        headers={"X-CSRF-Token": csrf},
        json={"ciscoClientSecret": ""},
    )
    assert again.status_code == 200
    assert secret_value(app.state.settings, "CISCO_API_CLIENT_SECRET") == secret
    assert secret not in again.text


def test_missing_eox_credentials_are_a_clear_message(tmp_path):
    client, _csrf, _app = _client(tmp_path)
    body = client.get("/api/v1/netbridge/eox").json()
    assert body["configured"] is False
    assert "Vault" in body["message"]
    assert body["rows"] == []


def test_fortimanager_and_netbox_writes_do_not_delete(tmp_path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        calls = []

        def _send(self, body: bytes):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            Handler.calls.append("GET")
            if self.path.rstrip("/").split("/")[-1].isdigit():
                self._send(b'{"id":1,"name":"keep-me","virtual_chassis":null,"primary_ip4":null,"custom_fields":{},"site":{"id":1,"name":"Lab"},"role":{"id":1,"name":"Access switch"}}')
                return
            self._send(b'{"results":[]}')

        def do_POST(self):
            Handler.calls.append("POST " + self.path.split("?")[0])
            self._send(b'{"id":4,"name":"created","results":[]}')

        def do_PATCH(self):
            Handler.calls.append("PATCH")
            self._send(b'{"id":1}')

        def do_DELETE(self):
            Handler.calls.append("DELETE")
            self._send(b"{}")

        def log_message(self, fmt, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = __import__("threading").Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        settings = _settings(tmp_path)
        settings = Settings(**{**settings.__dict__, "netbox_url": "http://127.0.0.1:%s" % port})
        from ie_config.netbridge.sources import apply_changes, fmg_list
        result = apply_changes(settings, [{
            "op": "create_device",
            "name": "ap-1",
            "serial": "FGL1",
            "model": "CW9164",
            "vendor": "Cisco",
            "site": "Lab",
            "role": "Access point",
            "ip": "",
        }])
        assert result["counts"]["created"] == 1
        assert "DELETE" not in Handler.calls
        assert any(call.startswith("POST /api/dcim/devices") for call in Handler.calls)

        def fmg(request: httpx.Request) -> httpx.Response:
            assert request.headers["authorization"] == "Bearer fmg-token"
            return httpx.Response(200, json={"result": [{"data": [{"name": "fg-1", "sn": "FGT123", "ip": "10.1.1.1"}]}]})

        listed = fmg_list("https://fmg.example", "fmg-token", http=httpx.Client(transport=httpx.MockTransport(fmg)))
        assert listed["ok"] is True
        assert listed["devices"][0]["serial"] == "FGT123"
        assert "fmg-token" not in json.dumps({k: v for k, v in listed.items() if k != "devices"} | {"n": len(listed["devices"])})
    finally:
        server.shutdown()


def test_paginate_reports_the_total():
    rows = [{"name": "ap-%04d" % n, "model": "CW9164" if n % 2 == 0 else "C9120"} for n in range(100)]
    page = paginate(rows, 2, 25, "c9120", ["name", "model"])
    assert page["total"] == 50
    assert page["page"] == 2
    assert len(page["rows"]) == 25


def _agent(table: dict[str, dict[str, str]]):
    def exchange(_host, _port, packet, _timeout):
        decoded = decode_message(packet)
        base = decoded["requested"]
        column = table.get(base) or {}
        keys = sorted(column, key=lambda item: tuple(int(part) for part in item.split(".")))
        binds = []
        for key in keys:
            oid = base + "." + key
            kind = "ip" if base == AIRE_IP else "str"
            binds.append((oid, value_for(kind, column[key])))
            if len(binds) == 20:
                break
        if not binds:
            from ie_config.netbridge.ber import varbind, tlv, enc_int, enc_str as es
            # One endOfMibView so the walk stops.
            end = tlv(0x30, __import__("ie_config.netbridge.ber", fromlist=["enc_oid"]).enc_oid(base + ".0") + b"\x82\x00")
            message = enc_int(1) + es(decoded["community"]) + tlv(0xA2, enc_int(decoded["request_id"]) + enc_int(0) + enc_int(0) + tlv(0x30, end))
            return tlv(0x30, message)
        return encode_response(decoded["community"], decoded["request_id"], binds)
    return exchange


def test_snmp_walk_joins_ap_fields():
    index = "0.17.223.1.2.3"
    table = {
        AIRE_NAME: {index: "ap-lobby"},
        AIRE_MODEL: {index: "CW9164I"},
        AIRE_SERIAL: {index: "FGL0001"},
        AIRE_IP: {index: "10.8.0.10"},
        CDP_AP: {"1": "ap-lobby"},
        CDP_NEIGH: {"1": "sw1.pnp.co.za"},
        CDP_PORT: {"1": "Gi1/0/4"},
    }
    result = scan_wlc("127.0.0.1", 1161, "public", exchange=_agent(table))
    assert result["ok"] is True
    assert result["aps"][0]["name"] == "ap-lobby"
    assert result["aps"][0]["model"] == "CW9164I"
    assert result["aps"][0]["serial"] == "FGL0001"
    assert result["aps"][0]["ip"] == "10.8.0.10"
    assert result["aps"][0]["neighbor"] == "sw1.pnp.co.za"
    assert result["aps"][0]["neighbor_port"] == "Gi1/0/4"
    packet = encode_getbulk("public", AIRE_NAME, 1, 10)
    assert decode_message(packet)["requested"] == AIRE_NAME
    assert b"public" in packet


def test_walk_handles_five_thousand_rows():
    names = {"%d" % n: "ap-%05d" % n for n in range(1, 5001)}

    def exchange(_host, _port, packet, _timeout):
        decoded = decode_message(packet)
        base = decoded["requested"]
        if not base.startswith(AIRE_NAME):
            from ie_config.netbridge.ber import enc_int, enc_oid, tlv
            end = tlv(0x30, enc_oid(base + ".0") + b"\x82\x00")
            message = enc_int(1) + enc_str(decoded["community"]) + tlv(0xA2, enc_int(decoded["request_id"]) + enc_int(0) + enc_int(0) + tlv(0x30, end))
            return tlv(0x30, message)
        current = tuple(int(part) for part in base.split("."))
        # The requested OID is the last returned one, or the column root.
        keys = sorted((int(key) for key in names), )
        # Determine the last index already walked from the requested oid.
        extra = decoded["requested"][len(AIRE_NAME):].strip(".")
        last = int(extra) if extra.isdigit() else 0
        binds = []
        for key in keys:
            if key <= last:
                continue
            binds.append((AIRE_NAME + ".%d" % key, value_for("str", names[str(key)])))
            if len(binds) == 25:
                break
        if not binds:
            from ie_config.netbridge.ber import enc_int, enc_oid, tlv
            end = tlv(0x30, enc_oid(base + ".0") + b"\x82\x00")
            message = enc_int(1) + enc_str("public") + tlv(0xA2, enc_int(decoded["request_id"]) + enc_int(0) + enc_int(0) + tlv(0x30, end))
            return tlv(0x30, message)
        return encode_response("public", decoded["request_id"], binds)

    rows = walk("127.0.0.1", 1161, "public", AIRE_NAME, max_reps=25, exchange=exchange)
    assert len(rows) == 5000
    assert rows[0][1] == "ap-00001"
    assert rows[-1][1] == "ap-05000"


def test_ise_tab_asks_for_credentials(tmp_path):
    client, _csrf, _app = _client(tmp_path)
    body = client.get("/api/v1/netbridge/ise").json()
    assert body["configured"] is False
    assert "Vault" in body["message"]
    assert body["rows"] == []
    assert body["activeSessions"] is None
    assert client.get("/api/v1/netbridge/open-count").json()["iseConfigured"] is False
    assert client.get("/api/v1/netbridge/open-count").json()["infobloxConfigured"] is False


def test_ise_pull_reads_version_count_and_sessions():
    from ie_config.netbridge.ise import pull

    password = "ise-password-value"
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        assert request.headers["authorization"].startswith("Basic ")
        assert password not in str(request.url)
        if request.url.path.endswith("/Version"):
            xml = "<product><version>3.3.0.430</version></product>"
        elif request.url.path.endswith("/ActiveCount"):
            xml = "<sessionCount><count>2</count></sessionCount>"
        else:
            assert "/AuthList/" in request.url.path
            assert "%20" in request.url.path
            xml = """
            <activeSessionList>
              <activeSession>
                <user_name>alex</user_name>
                <calling_station_id>AA:BB:CC:DD:EE:FF</calling_station_id>
                <nas_ip_address>10.129.32.16</nas_ip_address>
                <network_device_name>claremont-sw</network_device_name>
                <authentication_method>dot1x</authentication_method>
                <acs_server>ise-mnt</acs_server>
                <passed>true</passed>
                <failed>false</failed>
              </activeSession>
            </activeSessionList>
            """
        return httpx.Response(200, text=xml)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    body = pull("https://ise.example", "ers-admin", password, http=client)
    assert body["ok"] is True
    assert body["version"] == "3.3.0.430"
    assert body["activeSessions"] == 2
    assert body["rows"] == [{
        "user": "alex",
        "mac": "AA:BB:CC:DD:EE:FF",
        "nas": "10.129.32.16",
        "device": "claremont-sw",
        "method": "dot1x",
        "server": "ise-mnt",
        "result": "Passed",
    }]
    assert any(path.endswith("/Version") for path in seen)
    assert password not in json.dumps(body)


def test_ise_health_groups_admin_and_policy_nodes():
    from ie_config.netbridge.ise import health

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/Version"):
            return httpx.Response(200, text="<product><version>3.4.0.608</version></product>")
        if request.url.path.endswith("/ActiveCount"):
            return httpx.Response(200, text="<sessionCount><count>12</count></sessionCount>")
        assert request.url.path == "/api/v1/deployment/node"
        return httpx.Response(200, json={"response": [
            {"hostname": "pnp-psn1", "ipAddress": "10.96.1.152", "fqdn": "pnp-psn1.example", "nodeStatus": "Connected", "roles": [], "services": ["Session"]},
            {"hostname": "pnp-pan1", "ipAddress": "10.96.1.150", "fqdn": "pnp-pan1.example", "nodeStatus": "Connected", "roles": ["PrimaryAdmin"], "services": []},
            {"hostname": "pnp-mon2", "ipAddress": "10.97.1.151", "fqdn": "pnp-mon2.example", "nodeStatus": "NotReachable", "roles": ["PrimaryDedicatedMonitoring"], "services": []},
        ]})

    body = health("https://ise.example", "ers-admin", "secret-value", http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert body["ok"] is True
    assert body["version"] == "3.4.0.608"
    assert body["activeSessions"] == 12
    assert [node["hostname"] for node in body["nodes"]] == ["pnp-pan1", "pnp-mon2", "pnp-psn1"]
    assert body["nodes"][0]["group"] == "main"
    assert body["nodes"][0]["roles"] == ["Primary Admin"]
    assert body["nodes"][1]["healthy"] is False
    assert body["nodes"][1]["issues"] == ["Deployment status is NotReachable"]
    assert body["nodes"][0]["cpu"] is None
    assert body["nodes"][2]["group"] == "policy"
    assert body["nodes"][2]["roles"] == ["Policy Service"]
    assert "secret-value" not in json.dumps(body)


def test_ise_node_detail_only_opens_a_known_node():
    from ie_config.netbridge.ise import node_detail

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/Version"):
            return httpx.Response(200, text="<product><version>3.4.0.608</version></product>")
        if request.url.path == "/api/v1/deployment/node":
            return httpx.Response(200, json={"response": [
                {"hostname": "pnp-pan1", "ipAddress": "10.96.1.150", "fqdn": "pnp-pan1.example", "nodeStatus": "Connected", "roles": ["PrimaryAdmin"], "services": []},
            ]})
        return httpx.Response(404, text="")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    found = node_detail("https://ise.example", "ers-admin", "secret-value", "pnp-pan1", http=client, community="")
    assert found["ok"] is True
    assert found["node"]["fqdn"] == "pnp-pan1.example"
    assert found["node"]["cpus"] == []
    missing = node_detail("https://ise.example", "ers-admin", "secret-value", "../other", http=client, community="")
    assert missing["node"] is None
    assert "secret-value" not in json.dumps(found)


def test_ise_storage_entries_split_disks_and_memory():
    from ie_config.netbridge.ise import _storage_entries, _uptime

    descr = [("1.3.1", b"Physical memory"), ("1.3.55", b"/"), ("1.3.31", b"/run")]
    size = [("1.5.1", 100), ("1.5.55", 4), ("1.5.31", 10)]
    used = [("1.6.1", 80), ("1.6.55", 1), ("1.6.31", 1)]
    units = [("1.4.1", 1024), ("1.4.55", 1024), ("1.4.31", 1024)]
    disks = _storage_entries(descr, size, used, units, files=True)
    memory = _storage_entries(descr, size, used, units, files=False)
    assert [row["name"] for row in disks] == ["/"]
    assert disks[0]["percent"] == 25
    assert disks[0]["size"] == "4 KB"
    assert memory[0]["name"] == "Physical memory"
    assert _uptime(100 * (2 * 86400 + 3 * 3600)) == "2 days 3 hours"


def test_ise_resource_rows_become_cpu_memory_disk_and_services():
    from ie_config.netbridge.ise import _resources_from_rows

    body = _resources_from_rows(
        [("1.2.1", 10), ("1.2.2", 30)],
        [("1.3.1", b"Physical memory"), ("1.3.55", b"/"), ("1.3.66", b"/opt")],
        [("1.5.1", 100), ("1.5.55", 200), ("1.5.66", 50)],
        [("1.6.1", 91), ("1.6.55", 50), ("1.6.66", 10)],
        [("1.7.4", b"nginx"), ("1.7.9", b"redis-server")],
    )
    assert body["cpu"] == 20
    assert body["memory"] == 91
    assert body["diskRoot"] == 25
    assert body["diskOpt"] == 20
    assert body["services"] == [
        {"name": "Web", "running": True},
        {"name": "Cache", "running": True},
    ]
    assert body["issues"] == ["Memory is 91%"]
    assert body["ntp"] is False
    assert body["directory"] is False


def test_ise_operations_reads_sessions_inventory_and_dependencies():
    from datetime import datetime, timezone
    from ie_config.netbridge.ise import operations

    password = "ise-password-value"
    moment = datetime(2026, 11, 11, 20, 0, tzinfo=timezone.utc)

    def handler(request: httpx.Request) -> httpx.Response:
        assert password not in str(request.url)
        path = request.url.path
        if path.endswith("/Version"):
            return httpx.Response(200, text="<product><version>3.4.0.608</version></product>")
        if path.endswith("/ActiveCount"):
            return httpx.Response(200, text="<sessionCount><count>1200</count></sessionCount>")
        if "/AuthList/" in path:
            xml = """
            <activeSessionList>
              <activeSession>
                <user_name>alex</user_name>
                <calling_station_id>AA:BB:CC:DD:EE:FF</calling_station_id>
                <framed_ip_address>10.1.1.20</framed_ip_address>
                <nas_ip_address>10.129.32.16</nas_ip_address>
                <server>pnp-psn1</server>
              </activeSession>
            </activeSessionList>
            """
            return httpx.Response(200, text=xml)
        if path == "/ers/config/endpoint":
            return httpx.Response(200, json={"SearchResult": {"total": 50, "resources": []}})
        if path == "/ers/config/activedirectory/abc":
            return httpx.Response(200, json={"ERSActiveDirectory": {"name": "PnP-AD", "domain": "example.local"}})
        if path == "/ers/config/activedirectory":
            return httpx.Response(200, json={"SearchResult": {"total": 1, "resources": [
                {"name": "PnP-AD", "link": {"href": "https://evil.example/ers/config/activedirectory/abc"}},
            ]}})
        if path.startswith("/ers/config/"):
            return httpx.Response(200, json={"SearchResult": {"total": 3, "resources": []}})
        if path == "/api/v1/deployment/node":
            return httpx.Response(200, json={"response": [
                {"hostname": "pnp-pan1", "ipAddress": "10.96.1.150", "fqdn": "pnp-pan1.example", "nodeStatus": "Connected", "roles": ["PrimaryAdmin"], "services": []},
            ]})
        if path == "/api/v1/certs/trusted-certificate":
            return httpx.Response(200, json={"response": [
                {"friendlyName": "Old CA", "expirationDate": "2020-01-01T00:00:00.000+0000"},
                {"friendlyName": "Soon CA", "expirationDate": "2026-12-01T00:00:00.000+0000"},
                {"friendlyName": "Later CA", "expirationDate": "2027-06-01T00:00:00.000+0000"},
            ]})
        if path == "/admin/API/mnt/Alarm":
            return httpx.Response(404, text="")
        return httpx.Response(404, text=path)

    body = operations(
        "https://ise.example",
        "ers-admin",
        password,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        now=moment,
        resolve=lambda host: {"10.96.1.150"} if host == "pnp-pan1.example" else set(),
        probe=lambda ip: ip == "10.96.1.150",
    )
    assert body["ok"] is True
    assert body["sessions"]["active"] == 1200
    assert body["sessions"]["recent"] == 1
    assert body["sessions"]["rows"][0]["server"] == "pnp-psn1"
    assert body["sessions"]["rows"][0]["client"] == "10.1.1.20"
    assert body["sessions"]["message"] == ""
    inventory = {row["name"]: row["count"] for row in body["inventory"]}
    assert inventory["Endpoints"] == 50
    assert inventory["Network devices"] == 3
    assert inventory["Active Directory"] == 1
    assert body["directories"] == [{"name": "PnP-AD", "domain": "example.local"}]
    deps = {row["name"]: row for row in body["dependencies"]}
    assert deps["DNS"]["status"] == "ok"
    assert deps["DNS"]["rows"][0] == {"name": "pnp-pan1", "status": "ok", "detail": "Resolves to the deployment address."}
    assert deps["Reachability"]["rows"][0]["status"] == "ok"
    assert deps["Active Directory"]["status"] == "ok"
    assert "example.local" in deps["Active Directory"]["detail"]
    assert deps["Reachability"]["status"] == "ok"
    assert deps["Certificates"]["status"] == "warning"
    assert "expired" in deps["Certificates"]["detail"]
    assert body["alarms"]["available"] is False
    assert "secret" not in json.dumps(body)
    assert password not in json.dumps(body)
    from ie_config.netbridge.ise import _parse_time
    assert _parse_time("Wed Jun 01 00:00:00 SAST 2027").year == 2027


def test_infoblox_health_reads_grid_members_and_service_status():
    from ie_config.netbridge.infoblox import fetch, member_detail

    password = "infoblox-password"

    def handler(request: httpx.Request) -> httpx.Response:
        assert password not in str(request.url)
        path = request.url.path
        if "/wapi/v2.13.1/" in path:
            return httpx.Response(404, json={"Error": "unknown version"})
        if path.endswith("/grid"):
            assert path.startswith("/wapi/v2.12/")
            return httpx.Response(200, json=[{"name": "PnP"}])
        if path.endswith("/member"):
            return httpx.Response(200, json=[
                {
                    "host_name": "gm.example.com",
                    "platform": "VNIOS",
                    "vip_setting": {"address": "10.1.1.10"},
                    "service_status": [
                        {"service": "DNS", "status": "WORKING"},
                        {"service": "DHCP", "status": "FAILED"},
                        {"service": "TFTP", "status": "INACTIVE"},
                    ],
                    "node_info": [{"ha_status": "Active", "hwtype": "IB-V1425"}],
                },
                {
                    "host_name": "member.example.com",
                    "vip_setting": {"address": "10.1.1.11"},
                    "service_status": [{"service": "DNS", "status": "WORKING"}],
                    "node_info": [{"ha_status": "Not Configured"}],
                },
            ])
        return httpx.Response(404, text=path)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    body = fetch("https://10.1.1.10", "ibadmin", password, http=client)
    assert body["ok"] is True
    assert body["grid"] == "PnP"
    assert body["version"] == "v2.12"
    assert [row["hostname"] for row in body["members"]] == ["gm.example.com", "member.example.com"]
    master = body["members"][0]
    assert master["group"] == "grid"
    assert master["healthy"] is False
    assert master["services"] == [{"name": "DNS", "running": True}, {"name": "DHCP", "running": False}]
    assert "DHCP is failed" in master["issues"]
    assert "Active" in master["roles"]
    assert body["members"][1]["group"] == "member"
    assert body["members"][1]["healthy"] is True
    missing = member_detail("https://10.1.1.10", "ibadmin", password, "other.example.com", http=client)
    assert missing["member"] is None
    assert password not in json.dumps(body)

