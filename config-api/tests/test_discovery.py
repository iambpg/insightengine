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
