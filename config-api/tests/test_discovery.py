"""Discovery must not create NetBox devices until a person approves one."""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from sqlalchemy import select

from ie_config.db import DiscoveryCandidate, make_session_factory
from ie_config.discovery import (
    Discovery,
    NetBoxWriter,
    load_device_aliases,
    manufacturer_identity,
    site_for_ip,
    site_name_from_prefix,
)
from ie_config.settings import Settings

ROOT = Path(__file__).resolve().parents[2]


class NetBoxHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PATCH(self):
        self._handle("PATCH")

    def do_DELETE(self):
        self._handle("DELETE")

    def _handle(self, method):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        parsed = urlparse(self.path)
        self.server.calls.append((method, parsed.path, parse_qs(parsed.query), raw))
        fail = self.server.fail_on
        if fail and method == fail[0] and parsed.path.startswith(fail[1]):
            self._json(fail[2], {"detail": "no"})
            return
        if method == "GET" and parsed.path.startswith("/api/dcim/device-roles/") and getattr(self.server, "roles", None) is not None:
            query = parse_qs(parsed.query)
            slug = (query.get("slug") or [""])[0]
            name = (query.get("name__ie") or query.get("name") or [""])[0]
            roles = self.server.roles
            if slug:
                hits = [row for row in roles if row.get("slug") == slug]
            elif name:
                hits = [row for row in roles if str(row.get("name") or "").lower() == name.lower()]
            else:
                hits = []
            self._json(200, {"results": hits})
            return
        if method == "GET" and parsed.path.startswith("/api/dcim/device-types/") and getattr(self.server, "mode", "") == "alias":
            query = parse_qs(parsed.query)
            model = (query.get("model") or [""])[0]
            needle = (query.get("q") or [""])[0]
            if model == "Catalyst 3750-48TS":
                self._json(200, {"results": [{"id": 77, "model": "Catalyst 3750-48TS", "slug": "ws-c3750-48ts", "part_number": "WS-C3750-48TS-S"}]})
                return
            if needle:
                self._json(200, {"results": [
                    {"id": 78, "model": "Catalyst 3750-24TS", "slug": "ws-c3750-24ts"},
                    {"id": 77, "model": "Catalyst 3750-48TS", "slug": "ws-c3750-48ts"},
                ]})
                return
            self._json(200, {"results": []})
            return
        if method == "GET" and parsed.path.startswith("/api/dcim/device-types/") and "model" in parsed.query and "PA-820" in parsed.query:
            self._json(200, {"results": [{"id": 9, "slug": "pa-820", "model": "PA-820"}]})
            return
        if method == "GET":
            self._json(200, {"results": [{"id": 1, "name": "existing", "slug": "existing"}], "next": None})
            return
        if method == "POST" and parsed.path.startswith("/api/dcim/devices"):
            self._json(201, {"id": 10, "name": "edge"})
            return
        if method == "POST" and parsed.path.startswith("/api/dcim/interfaces"):
            self._json(201, {"id": 20, "name": "mgmt"})
            return
        if method == "POST" and "ip-addresses" in parsed.path:
            self._json(201, {"id": 30, "address": "10.1.1.1/32"})
            return
        if method == "DELETE":
            self._json(204, None)
            return
        self._json(200, {"id": 10})

    def _json(self, status, body):
        data = b"" if body is None else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if data:
            self.wfile.write(data)

    def log_message(self, fmt, *args):
        return


def _server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), NetBoxHandler)
    server.calls = []
    server.fail_on = None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _settings(tmp_path: Path, base: str) -> Settings:
    token = tmp_path / "token"
    token.write_text("nbt_citoken12345.0123456789abcdef0123456789abcdef0fedcba9", encoding="utf-8")
    cfg = tmp_path / "config" / "discovery"
    cfg.mkdir(parents=True)
    (cfg / "sync.yml").write_text(
        "prefix_selector: tag\ntag: ie-scan\ninterval_hours: 6\nprefix_poll_seconds: 60\n"
        "snmp_timeout_us: 1000000\nsnmp_retries: 1\nsnmp_try_slow_connect: false\n",
        encoding="utf-8",
    )
    nd = tmp_path / "config" / "netdisco"
    nd.mkdir(parents=True)
    (nd / "deployment.yml").write_text(
        "snmptimeout: ${SNMP_TIMEOUT_US}\nsnmpretries: ${SNMP_RETRIES}\n"
        "snmp_try_slow_connect: ${SNMP_TRY_SLOW}\ndevice_auth:\n  - community: ${SNMP_V2_COMMUNITY}\n",
        encoding="utf-8",
    )
    return Settings(
        config_root=str(tmp_path),
        apps_file=str(tmp_path / "apps.yml"),
        database_url="sqlite:///" + str(tmp_path / "ie.db"),
        history_dir=str(tmp_path / "history"),
        cookie_secure=False,
        cookie_name="ie_session",
        setup_token_file=str(tmp_path / "setup"),
        client_slug="test",
        public_host="localhost",
        docker_proxy_url="http://127.0.0.1:9",
        scheduler=False,
        netbox_url=base,
        netbox_token_file=str(token),
        netdisco_database_url="",
        netdisco_out_dir=str(tmp_path / "nd"),
        mib_dir=str(tmp_path / "mibs"),
        candidate_dir=str(tmp_path / "cand"),
        generator_bin="missing",
    )


def test_site_comes_from_the_most_specific_prefix():
    prefixes = [
        {"prefix": "10.0.0.0/8", "status": "active", "scope_type": "dcim.site", "scope": {"name": "Wide", "slug": "wide"}},
        {"prefix": "10.1.0.0/16", "status": "active", "scope_type": "dcim.region", "scope": {"name": "North", "slug": "north"}},
        {"prefix": "10.1.1.0/24", "status": "active", "site": {"name": "Test Site", "slug": "test-site"}},
    ]
    assert site_name_from_prefix(prefixes[1]) == ""
    assert site_for_ip("10.1.1.9", prefixes) == "Test Site"
    assert site_for_ip("10.2.0.1", prefixes) == "Wide"
    assert site_for_ip("192.0.2.1", prefixes) == ""


def test_palo_alto_slug_matches_the_library():
    name, slug = manufacturer_identity("Palo Alto Networks", {})
    assert slug == "palo-alto"
    assert name == "Palo Alto Networks"
    name, slug = manufacturer_identity("cisco", {"manufacturer_slug": "cisco"})
    assert slug == "cisco"


def test_refresh_does_not_create_netbox_devices(tmp_path, monkeypatch):
    server = _server()
    try:
        settings = _settings(tmp_path, "http://127.0.0.1:%s" % server.server_address[1])
        factory, _engine = make_session_factory(settings.database_url)
        discovery = Discovery(settings, factory, settings.config_root)
        monkeypatch.setattr(
            discovery,
            "fetch_netdisco_devices",
            lambda: [{"ip": "10.1.1.9", "name": "sw1", "sysdescr": "Cisco", "vendor": "Cisco", "model": "C9300", "sysobjectid": ""}],
        )
        # Prefix list is what makes the address eligible. No device is posted.
        (tmp_path / "nd").mkdir()
        (tmp_path / "nd" / "scan-prefixes.txt").write_text("10.1.1.0/24\n", encoding="utf-8")
        result = discovery.refresh_unapproved()
        assert result["ok"] is True
        assert result["added"] == 1
        posts = [call for call in server.calls if call[0] == "POST"]
        assert posts == []
        rows = discovery.list_unapproved()
        assert rows[0]["ip"] == "10.1.1.9"
        assert rows[0]["status"] == "pending"
    finally:
        server.shutdown()


def test_pending_removed_when_prefix_goes_away_or_ip_is_in_netbox(tmp_path, monkeypatch):
    server = _server()
    try:
        settings = _settings(tmp_path, "http://127.0.0.1:%s" % server.server_address[1])
        factory, _engine = make_session_factory(settings.database_url)
        discovery = Discovery(settings, factory, settings.config_root)
        with factory() as db:
            db.add(DiscoveryCandidate(ip="10.1.1.9", name="sw1", status="pending", role_slug="access-switch", site_slug="Test Site"))
            db.add(DiscoveryCandidate(ip="10.9.9.9", name="old", status="pending", role_slug="access-switch"))
            db.add(DiscoveryCandidate(ip="10.1.1.8", name="kept-rejected", status="rejected"))
            db.commit()
        (tmp_path / "nd").mkdir()
        (tmp_path / "nd" / "scan-prefixes.txt").write_text("10.1.1.0/24\n10.9.9.0/24\n", encoding="utf-8")
        monkeypatch.setattr(discovery, "fetch_prefixes", lambda: [
            {"prefix": "10.1.1.0/24", "status": "active", "tags": [{"slug": "ie-scan"}], "site": {"name": "Test Site", "slug": "test-site"}},
        ])
        synced = discovery.sync_prefixes()
        assert "10.9.9.0/24" in synced["removed"]
        assert discovery.list_unapproved()[0]["ip"] == "10.1.1.9"
        monkeypatch.setattr(discovery, "fetch_netbox_ips", lambda: {"10.1.1.9"})
        monkeypatch.setattr(discovery, "fetch_netdisco_devices", lambda: [
            {"ip": "10.1.1.9", "name": "sw1", "sysdescr": "", "vendor": "Cisco", "model": "C9300", "sysobjectid": ""},
        ])
        refreshed = discovery.refresh_unapproved()
        assert refreshed["removed"] >= 1
        assert discovery.list_unapproved() == []
        with factory() as db:
            rejected = db.scalar(select(DiscoveryCandidate).where(DiscoveryCandidate.ip == "10.1.1.8"))
            assert rejected is not None and rejected.status == "rejected"
        posts = [call for call in server.calls if call[0] == "POST" and call[1].startswith("/api/dcim/devices")]
        assert posts == []
    finally:
        server.shutdown()


def test_deleted_netbox_device_can_be_approved_again(tmp_path, monkeypatch):
    server = _server()
    try:
        settings = _settings(tmp_path, "http://127.0.0.1:%s" % server.server_address[1])
        factory, _engine = make_session_factory(settings.database_url)
        discovery = Discovery(settings, factory, settings.config_root)
        with factory() as db:
            db.add(DiscoveryCandidate(
                ip="10.1.1.9", name="sw1", status="approved", role_slug="Access switch",
                site_slug="Test Site", netbox_device_id="55",
            ))
            db.commit()
        (tmp_path / "nd").mkdir()
        (tmp_path / "nd" / "scan-prefixes.txt").write_text("10.1.1.0/24\n", encoding="utf-8")
        monkeypatch.setattr(discovery, "fetch_netbox_ips", lambda: set())
        monkeypatch.setattr(discovery, "fetch_netbox_ids", lambda: set())
        monkeypatch.setattr(discovery, "fetch_netdisco_devices", lambda: [
            {"ip": "10.1.1.9", "name": "sw1", "sysdescr": "", "vendor": "Cisco", "model": "C9300", "sysobjectid": ""},
        ])
        discovery.refresh_unapproved()
        rows = discovery.list_unapproved()
        assert [row["ip"] for row in rows] == ["10.1.1.9"]
        assert rows[0]["status"] == "pending"
        assert rows[0]["netboxDeviceId"] is None
    finally:
        server.shutdown()


def test_discovery_stores_the_hostname_without_the_domain(tmp_path, monkeypatch):
    server = _server()
    try:
        settings = _settings(tmp_path, "http://127.0.0.1:%s" % server.server_address[1])
        factory, _engine = make_session_factory(settings.database_url)
        discovery = Discovery(settings, factory, settings.config_root)
        (tmp_path / "nd").mkdir()
        (tmp_path / "nd" / "scan-prefixes.txt").write_text("10.1.1.0/24\n", encoding="utf-8")
        monkeypatch.setattr(discovery, "hostname_suffixes", lambda: [".pnp.co.za", ".verginactive.co.za"])
        monkeypatch.setattr(discovery, "fetch_netbox_ips", lambda: set())
        monkeypatch.setattr(discovery, "fetch_netbox_ids", lambda: set())
        monkeypatch.setattr(discovery, "fetch_netdisco_devices", lambda: [
            {"ip": "10.1.1.9", "name": "wc00-kenilworth-asw01.pnp.co.za", "sysdescr": "", "vendor": "Cisco", "model": "C9200", "sysobjectid": ""},
            {"ip": "10.1.1.10", "name": "gym-sw01.verginactive.co.za", "sysdescr": "", "vendor": "Cisco", "model": "C9200", "sysobjectid": ""},
        ])
        discovery.refresh_unapproved()
        by_ip = {row["ip"]: row["name"] for row in discovery.list_unapproved()}
        assert by_ip["10.1.1.9"] == "wc00-kenilworth-asw01"
        assert by_ip["10.1.1.10"] == "gym-sw01"
    finally:
        server.shutdown()


def test_chassis_part_number_is_shown_as_the_model(tmp_path, monkeypatch):
    server = _server()
    try:
        settings = _settings(tmp_path, "http://127.0.0.1:%s" % server.server_address[1])
        factory, _engine = make_session_factory(settings.database_url)
        discovery = Discovery(settings, factory, settings.config_root)
        (tmp_path / "nd").mkdir()
        (tmp_path / "nd" / "scan-prefixes.txt").write_text("10.1.1.0/24\n", encoding="utf-8")
        monkeypatch.setattr(discovery, "fetch_netbox_ips", lambda: set())
        monkeypatch.setattr(discovery, "fetch_netbox_ids", lambda: set())
        monkeypatch.setattr(discovery, "fetch_netdisco_devices", lambda: [
            {"ip": "10.1.1.9", "name": "fg", "sysdescr": "", "vendor": "fortinet", "model": "60F", "part": "FGT_60F", "sysobjectid": ""},
            {"ip": "10.1.1.10", "name": "sw", "sysdescr": "", "vendor": "cisco", "model": "296024PC", "part": "WS-C2960-24PC-L", "sysobjectid": ""},
        ])
        discovery.refresh_unapproved()
        by_ip = {row["ip"]: row["model"] for row in discovery.list_unapproved()}
        assert by_ip["10.1.1.9"] == "FG-60F"
        assert by_ip["10.1.1.10"] == "WS-C2960-24PC-L"
    finally:
        server.shutdown()


def test_approve_looks_up_the_device_type_by_part_number(tmp_path):
    server = _server()
    try:
        base = "http://127.0.0.1:%s" % server.server_address[1]
        writer = NetBoxWriter(base, {"Authorization": "Bearer nbt_citoken12345.secret"})
        writer.approve_device(
            {"ip": "10.1.1.9", "name": "fg", "vendor": "fortinet", "model": "FGT_60F", "site": "Test Site"},
            {"role": "firewall"},
            {},
        )
        looked = [
            call[2].get("part_number", [""])[0]
            for call in server.calls
            if call[0] == "GET" and call[1].startswith("/api/dcim/device-types")
        ]
        assert looked[0] == "FG-60F"
    finally:
        server.shutdown()


def test_approve_creates_interface_then_ip_then_primary_and_rolls_back(tmp_path):
    server = _server()
    try:
        base = "http://127.0.0.1:%s" % server.server_address[1]
        writer = NetBoxWriter(base, {"Authorization": "Bearer nbt_citoken12345.secret"})
        created = writer.approve_device(
            {"ip": "10.1.1.9", "name": "sw1", "vendor": "Palo Alto Networks", "model": "PA-820", "site": "Test Site"},
            {"role": "Access switch", "platform": "PAN-OS", "model": "unknown"},
            {},
        )
        assert created["device_id"] == 10
        assert created["site"] == "test-site"
        assert created["role"] == "access-switch"
        methods = [(call[0], call[1]) for call in server.calls]
        device_at = methods.index(("POST", "/api/dcim/devices/"))
        iface_at = methods.index(("POST", "/api/dcim/interfaces/"))
        ip_at = next(i for i, call in enumerate(methods) if call[0] == "POST" and call[1].startswith("/api/ipam/ip-addresses"))
        patch_at = next(i for i, call in enumerate(methods) if call[0] == "PATCH")
        assert device_at < iface_at < ip_at < patch_at
        ip_body = json.loads(server.calls[ip_at][3])
        assert ip_body["assigned_object_type"] == "dcim.interface"
        assert ip_body["assigned_object_id"] == 20
        slug_query = [call[2].get("slug", [""])[0] for call in server.calls if call[0] == "GET"]
        assert "palo-alto" in slug_query
        assert "test-site" in slug_query

        server.calls.clear()
        server.fail_on = ("POST", "/api/ipam/ip-addresses", 400)
        try:
            writer.approve_device(
                {"ip": "10.1.1.9", "name": "sw1", "vendor": "Cisco", "model": "no-such-model", "site": "Test Site"},
                {"role": "access-switch"},
                {},
            )
            raise AssertionError("approve should have failed")
        except RuntimeError:
            pass
        assert any(call[0] == "DELETE" and call[1].startswith("/api/dcim/devices/") for call in server.calls)
    finally:
        server.shutdown()


def test_rendered_deployment_writes_domain_suffix_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("HOSTNAME_STRIP_SUFFIXES", ".pnp.co.za, example.net")
    settings = _settings(tmp_path, "http://127.0.0.1:9")
    factory, _engine = make_session_factory(settings.database_url)
    discovery = Discovery(settings, factory, settings.config_root)
    discovery.render_deployment()
    text = (Path(settings.netdisco_out_dir) / "deployment.yml").read_text(encoding="utf-8")
    assert "domain_suffix:" in text
    assert "- '.pnp.co.za'" in text
    assert "- '.example.net'" in text
    assert text.index("domain_suffix:") < text.index("snmptimeout:")


def test_approve_reuses_a_role_whose_slug_is_not_the_display_name(tmp_path):
    server = _server()
    server.roles = [{"id": 5, "name": "Core Switch", "slug": "core-switches"}]
    try:
        base = "http://127.0.0.1:%s" % server.server_address[1]
        writer = NetBoxWriter(base, {"Authorization": "Bearer nbt_citoken12345.secret"})
        created = writer.approve_device(
            {
                "ip": "10.129.32.1",
                "name": "wc18.cc30-claremont-1rsw01",
                "vendor": "Cisco",
                "model": "WS-C3560CG-8TC-S",
                "site": "wc18",
            },
            {"role": "Core Switch"},
            {},
        )
        assert created["device_id"] == 10
        role_posts = [
            call for call in server.calls
            if call[0] == "POST" and call[1].startswith("/api/dcim/device-roles")
        ]
        assert role_posts == []
        device = json.loads(next(
            call[3] for call in server.calls
            if call[0] == "POST" and call[1].startswith("/api/dcim/devices")
        ))
        assert device["name"] == "wc18.cc30-claremont-1rsw01"
        assert device["role"] == 5
    finally:
        server.shutdown()


def test_approve_strips_the_domain_suffix_from_the_netbox_name(tmp_path, monkeypatch):
    monkeypatch.setenv("HOSTNAME_STRIP_SUFFIXES", ".pnp.co.za")
    server = _server()
    try:
        base = "http://127.0.0.1:%s" % server.server_address[1]
        writer = NetBoxWriter(base, {"Authorization": "Bearer nbt_citoken12345.secret"})
        writer.approve_device(
            {"ip": "10.129.32.16", "name": "wc18.cc30-claremont-1rsw01.pnp.co.za", "vendor": "Cisco", "model": "WS-C2960-24PC-L", "site": "Claremont"},
            {"role": "access-switch"},
            {},
            suffixes=[".pnp.co.za"],
        )
        posted = json.loads(next(call[3] for call in server.calls if call[0] == "POST" and call[1].startswith("/api/dcim/devices")))
        assert posted["name"] == "wc18.cc30-claremont-1rsw01"
    finally:
        server.shutdown()


def test_rendered_deployment_is_readable_by_netdisco(tmp_path):
    settings = _settings(tmp_path, "http://127.0.0.1:9")
    factory, _engine = make_session_factory(settings.database_url)
    discovery = Discovery(settings, factory, settings.config_root)
    discovery.render_deployment()
    path = Path(settings.netdisco_out_dir) / "deployment.yml"
    text = path.read_text(encoding="utf-8")
    assert "snmptimeout: 1000000" in text
    assert "snmpretries: 1" in text
    assert "snmp_try_slow_connect: false" in text
    mode = path.stat().st_mode & 0o777
    uid = path.stat().st_uid
    assert uid == 901 or mode & 0o044
    assert os.access(path, os.R_OK)


def test_netdisco_family_model_reuses_library_type(tmp_path):
    server = _server()
    server.mode = "alias"
    try:
        base = "http://127.0.0.1:%s" % server.server_address[1]
        aliases = {
            "37xxstack": {
                "prefer": ["Catalyst 3750-48TS"],
                "contains": ["3750"],
            }
        }
        writer = NetBoxWriter(base, {"Authorization": "Bearer nbt_example.secret"})
        created = writer.approve_device(
            {"ip": "10.1.1.9", "name": "stack1", "vendor": "cisco", "model": "37xxStack", "site": "Test Site"},
            {"role": "access-switch"},
            {},
            aliases,
        )
        assert created["device_id"] == 10
        posted = [call for call in server.calls if call[0] == "POST" and call[1].startswith("/api/dcim/devices")]
        body = json.loads(posted[0][3])
        assert body["device_type"] == 77
        assert not any(call[0] == "POST" and call[1].startswith("/api/dcim/device-types") for call in server.calls)
    finally:
        server.shutdown()


def test_alias_file_normalizes_netdisco_names():
    aliases = load_device_aliases(str(ROOT / "config" / "discovery" / "device-type-aliases.yml"))
    assert "3750" in aliases["37xxstack"]["contains"]
    assert aliases["37xxstack"]["prefer"][0] == "Catalyst 3750-48TS"


def test_queued_scan_is_finished_after_the_scheduler(tmp_path):
    settings = _settings(tmp_path, "http://127.0.0.1:9")
    factory, _engine = make_session_factory(settings.database_url)
    discovery = Discovery(settings, factory, settings.config_root)
    (tmp_path / "nd").mkdir()
    created = discovery.queue_manual_scan("prefix", "10.2.0.0/24")
    other = discovery.queue_manual_scan("prefix", "10.3.0.0/24")
    assert created["status"] == "queued"
    # A global stamp must not close every queued scan.
    (tmp_path / "nd" / "scan-finished").write_text("2099-01-01T00:00:00Z\n", encoding="utf-8")
    assert discovery.note_scans_finished() == 0
    stamp = "2099-01-01T00:00:00Z"
    done = tmp_path / "nd" / "scan-done"
    done.mkdir()
    (done / created["id"]).write_text(stamp + "\nfinished\nNetdisco finished that probe.\n", encoding="utf-8")
    assert discovery.note_scans_finished() == 1
    rows = {row["id"]: row for row in discovery.list_scans()}
    assert rows[created["id"]]["status"] == "finished"
    assert rows[created["id"]]["finishedAt"] == stamp
    assert rows[other["id"]]["status"] == "queued"


def test_single_ip_scan_does_not_raise_scan_now(tmp_path):
    settings = _settings(tmp_path, "http://127.0.0.1:9")
    factory, _engine = make_session_factory(settings.database_url)
    discovery = Discovery(settings, factory, settings.config_root)
    (tmp_path / "nd").mkdir()
    created = discovery.queue_manual_scan("ip", "10.9.9.9")
    text = (tmp_path / "nd" / "scan-once.txt").read_text(encoding="utf-8")
    assert text.startswith(created["id"] + " ")
    assert "10.9.9.9/32" in text
    assert not (tmp_path / "nd" / "scan-now").exists()


def test_backend_restarts_only_when_deployment_changes(tmp_path):
    settings = _settings(tmp_path, "http://127.0.0.1:9")
    factory, _engine = make_session_factory(settings.database_url)
    discovery = Discovery(settings, factory, settings.config_root)
    calls = []
    discovery.restart_backend = lambda: calls.append("restart") or True
    discovery.render_deployment()
    assert calls == ["restart"]
    discovery.render_deployment()
    assert calls == ["restart"]
    template = tmp_path / "config" / "netdisco" / "deployment.yml"
    template.write_text("device_auth:\n  - tag: default\n    community: other\n", encoding="utf-8")
    discovery.render_deployment()
    assert calls == ["restart", "restart"]


def test_bearer_header_for_v2_token(tmp_path):
    settings = _settings(tmp_path, "http://127.0.0.1:9")
    factory, _engine = make_session_factory(settings.database_url)
    discovery = Discovery(settings, factory, settings.config_root)
    headers = discovery.netbox_headers()
    assert headers["Authorization"].startswith("Bearer nbt_")
    v1 = tmp_path / "v1"
    v1.write_text("0123456789abcdef0123456789abcdef01234567\n", encoding="utf-8")
    settings_v1 = Settings(**{**settings.__dict__, "netbox_token_file": str(v1)})
    other = Discovery(settings_v1, factory, settings.config_root)
    assert other.netbox_headers()["Authorization"].startswith("Token ")


def _ready(discovery, monkeypatch):
    monkeypatch.setenv("SNMP_V2_COMMUNITY", "s3cret-community")
    discovery._snmp_sync = lambda: None
    discovery.restart_backend = lambda: False


def test_snmp_precheck_hides_the_community_and_names_the_profile(tmp_path, monkeypatch):
    settings = _settings(tmp_path, "http://127.0.0.1:9")
    factory, _engine = make_session_factory(settings.database_url)
    discovery = Discovery(settings, factory, settings.config_root)
    _ready(discovery, monkeypatch)
    seen = []

    def probe(profile, host, auth):
        seen.append((host, auth, profile.get("community")))
        return {"ok": False, "error": "timeout", "leak": profile.get("community")}

    failed = discovery.snmp_precheck("10.9.9.9", probe=probe)
    assert failed["ok"] is False
    assert "s3cret-community" not in failed["message"]
    assert "timed out" in failed["message"]
    assert seen and seen[0][2] == "s3cret-community"

    def ok_probe(profile, host, auth):
        return {"ok": True, "version": "2c"}

    reached = discovery.snmp_precheck("10.9.9.9", probe=ok_probe)
    assert reached == {
        "ok": True,
        "profile": "default",
        "message": "SNMP reachable via profile default",
    }


def test_device_job_dedupes_and_maps_netdisco_status(tmp_path, monkeypatch):
    from ie_config.netdisco_jobs import MemoryAdmin, map_admin_status

    settings = _settings(tmp_path, "http://127.0.0.1:9")
    factory, _engine = make_session_factory(settings.database_url)
    discovery = Discovery(settings, factory, settings.config_root)
    _ready(discovery, monkeypatch)
    jobs = MemoryAdmin()
    jobs.neighbours["10.1.1.8"] = ["10.1.1.9", "not-an-ip"]

    assert map_admin_status("queued", None, "") == "queued"
    assert map_admin_status("queued", "t", "backend") == "running"
    assert map_admin_status("done", "t", "backend") == "done"
    assert map_admin_status("error", "t", "") == "error"
    assert map_admin_status("info", None, "") == "error"

    failed = discovery.start_device_discover(
        "10.1.1.8",
        neighbours=True,
        probe=lambda profile, host, auth: {"ok": False, "error": "timeout"},
        jobs=jobs,
    )
    assert failed["status"] == "error"
    assert "s3cret-community" not in failed["message"]
    assert jobs.rows == []

    created = discovery.start_device_discover(
        "10.1.1.8",
        neighbours=True,
        probe=lambda profile, host, auth: {"ok": True},
        jobs=jobs,
    )
    assert created["status"] == "queued"
    assert created["steps"][0]["message"] == "SNMP reachable via profile default"
    assert [step["name"] for step in created["steps"][:4]] == ["snmp", "discover", "macsuck", "arpnip"]
    again = discovery.start_device_discover(
        "10.1.1.8",
        neighbours=True,
        probe=lambda profile, host, auth: {"ok": True},
        jobs=jobs,
    )
    assert again["id"] == created["id"]
    assert len([row for row in jobs.rows if row["action"] == "discover"]) == 1

    jobs.set_state(jobs.rows[0]["id"], "queued", started="now", backend="worker")
    running = discovery.device_job_status(int(created["id"]), jobs=jobs)
    assert running["status"] == "running"
    assert running["steps"][1]["status"] == "running"

    jobs.set_state(jobs.rows[0]["id"], "error", log="discover failed: could not SNMP connect", started="now", finished="done", backend="worker")
    errored = discovery.device_job_status(int(created["id"]), jobs=jobs)
    assert errored["status"] == "error"
    assert errored["message"] == "discover failed: could not SNMP connect"
    assert "s3cret-community" not in errored["message"]
    assert all(step["status"] == "error" for step in errored["steps"] if step["name"] in ("macsuck", "arpnip"))

    jobs2 = MemoryAdmin()
    jobs2.neighbours["10.2.2.2"] = ["10.2.2.3"]
    fresh = discovery.start_device_discover(
        "10.2.2.2",
        neighbours=True,
        probe=lambda profile, host, auth: {"ok": True},
        jobs=jobs2,
    )
    jobs2.set_state(jobs2.rows[0]["id"], "done", log="Successful discover for new device", started="now", finished="done", backend="worker")
    mid = discovery.device_job_status(int(fresh["id"]), jobs=jobs2)
    assert mid["status"] == "running"
    actions = [row["action"] for row in jobs2.rows]
    assert actions.count("discover") == 2  # device plus one neighbour
    assert "macsuck" in actions and "arpnip" in actions
    for row in jobs2.rows:
        if row["raw_status"] != "done":
            jobs2.set_state(row["id"], "done", log="ok", started="now", finished="done", backend="worker")
    done = discovery.device_job_status(int(fresh["id"]), jobs=jobs2)
    assert done["status"] == "done"
    assert any(step.get("ip") == "10.2.2.3" for step in done["steps"])
    assert "not-an-ip" not in str(done)


def test_skipped_macsuck_does_not_stay_queued(tmp_path, monkeypatch):
    from ie_config.netdisco_jobs import MemoryAdmin

    settings = _settings(tmp_path, "http://127.0.0.1:9")
    factory, _engine = make_session_factory(settings.database_url)
    discovery = Discovery(settings, factory, settings.config_root)
    _ready(discovery, monkeypatch)
    jobs = MemoryAdmin()
    jobs.skipped = {"10.4.4.4": ["macsuck", "arpnip"]}
    created = discovery.start_device_discover(
        "10.4.4.4",
        probe=lambda profile, host, auth: {"ok": True},
        jobs=jobs,
    )
    jobs.set_state(jobs.rows[0]["id"], "done", log="Successful discover for new device", started="now", finished="done", backend="worker")
    done = discovery.device_job_status(int(created["id"]), jobs=jobs)
    assert done["status"] == "done", done
    assert "skipped macsuck" in done["steps"][2]["message"]
    assert "skipped arpnip" in done["steps"][3]["message"]


def test_scheduler_runs_scan_once_before_prefixes(tmp_path):
    import os
    import subprocess

    script = ROOT / "scripts" / "netdisco-scheduler.sh"
    work = tmp_path / "sched"
    bindir = work / "bin"
    bindir.mkdir(parents=True)
    log = work / "log"
    (bindir / "perl").write_text(
        "#!/bin/sh\n"
        "echo \"presweep $2\" >> \"$LOG\"\n"
        "if [ \"${DROP:-}\" = 1 ]; then exit 0; fi\n"
        "case \"$2\" in\n"
        "  */32) printf '%s\\n' \"${2%/32}\" ;;\n"
        "  *) printf '%s\\n' \"$(printf '%s' \"$2\" | sed 's/\\.0\\/[0-9]*$/.1/')\" ;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    (bindir / "netdisco-do").write_text(
        "#!/bin/sh\n"
        "echo \"netdisco-do $*\" >> \"$LOG\"\n"
        "if [ \"${FAIL_ACTION:-}\" = \"$1\" ]; then exit 3; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    os.chmod(bindir / "perl", 0o755)
    os.chmod(bindir / "netdisco-do", 0o755)
    (work / "presweep.pl").write_text("", encoding="utf-8")
    (work / "scan-once.txt").write_text("7 10.9.9.9/32\n", encoding="utf-8")
    (work / "scan-prefixes.txt").write_text("10.2.0.0/24\n", encoding="utf-8")
    (work / "scan-now").write_text("now\n", encoding="utf-8")
    env = os.environ.copy()
    env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
    env["NETDISCO_LOCAL_DIR"] = str(work)
    env["PRESWEEP_BIN"] = str(work / "presweep.pl")
    env["LOG"] = str(log)
    result = subprocess.run(["sh", str(script), "--once"], env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    lines = log.read_text(encoding="utf-8").splitlines()
    assert lines.index("presweep 10.9.9.9/32") < lines.index("presweep 10.2.0.0/24")
    assert "netdisco-do discover -d 10.9.9.9" in lines
    assert not (work / "scan-now").exists()
    done = (work / "scan-done" / "7").read_text(encoding="utf-8")
    assert "finished" in done

    env["DROP"] = "1"
    (work / "scan-once.txt").write_text("8 10.8.8.8/32\n", encoding="utf-8")
    (work / "scan-prefixes.txt").unlink()
    dropped = subprocess.run(["sh", str(script), "--once"], env=env, capture_output=True, text=True, check=False)
    assert dropped.returncode == 0, dropped.stderr
    assert "presweep dropped 10.8.8.8/32" in dropped.stderr
    failed = (work / "scan-done" / "8").read_text(encoding="utf-8")
    assert failed.splitlines()[1] == "failed"

    env.pop("DROP")
    env["FAIL_ACTION"] = "discover"
    (work / "scan-once.txt").write_text("9 10.7.7.7/32\n", encoding="utf-8")
    broken = subprocess.run(["sh", str(script), "--once"], env=env, capture_output=True, text=True, check=False)
    assert broken.returncode == 0, broken.stderr
    assert "netdisco-do discover failed for 10.7.7.7" in broken.stderr
    assert (work / "scan-done" / "9").read_text(encoding="utf-8").splitlines()[1] == "failed"
