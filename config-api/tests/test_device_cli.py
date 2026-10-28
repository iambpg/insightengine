"""Read-only device CLI and the apps launcher. SSH and upstreams are mocked."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from ie_config.app import create_app
from ie_config.apps_launcher import build_catalog, public_base
from ie_config.db import AuditRow
from ie_config.device_cli import platform_for, resolve_command
from ie_config.errors import ApiError
from ie_config.fleet import FleetService, redact_config
from ie_config.settings import Settings


def test_allowlist_rejects_config_mode_and_pipes():
    assert platform_for("IOS-XE 17.9", "Cisco") == "ios"
    assert platform_for("NX-OS", "Cisco") == "nxos"
    assert platform_for("FortiOS", "Fortinet") == "fortigate"
    assert platform_for("PAN-OS", "Palo Alto") == "panos"
    assert resolve_command("ios", "  show   version ") == "show version"
    with pytest.raises(ApiError) as pipe:
        resolve_command("ios", "show version | include Cisco")
    assert pipe.value.code == "bad_command"
    with pytest.raises(ApiError) as config:
        resolve_command("ios", "configure terminal")
    assert config.value.code == "command_not_allowed"
    with pytest.raises(ApiError) as running:
        resolve_command("fortigate", "show full-configuration")
    assert running.value.code == "command_not_allowed"
    assert resolve_command("fortigate", "get system status") == "get system status"
    with pytest.raises(ApiError) as unknown:
        resolve_command("", "show version")
    assert unknown.value.code == "unsupported_platform"


def test_backup_redaction_drops_the_secret_value():
    text = "hostname core-1\npassword 7 0822455C0A\nsnmp-server community public RO\ninterface Gi1/0/1"
    cleaned = redact_config(text)
    assert "0822455C0A" not in cleaned
    assert "public" not in cleaned
    assert "hostname core-1" in cleaned


def test_public_urls_use_the_published_ports(monkeypatch):
    monkeypatch.setenv("PORT_HTTPS", "57400")
    monkeypatch.setenv("PORT_GRAFANA", "13000")
    monkeypatch.setenv("PORT_PROMETHEUS", "19090")
    monkeypatch.setenv("PORT_ALERTMANAGER", "19093")
    monkeypatch.setenv("PORT_ACTIVEPIECES", "18081")
    monkeypatch.setenv("PORT_NETDISCO", "15000")
    monkeypatch.setenv("PORT_OXIDIZED", "18888")
    monkeypatch.setenv("PORT_NETBOX", "18444")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    body = build_catalog("monitor.example.com", "Engineer", client)
    urls = {row["id"]: row["url"] for row in body["apps"]}
    assert urls["ui"] == "https://monitor.example.com:57400/"
    assert urls["grafana"] == "https://monitor.example.com:13000/"
    assert urls["prometheus"] == "https://monitor.example.com:19090/"
    assert urls["alertmanager"] == "https://monitor.example.com:19093/"
    assert urls["activepieces"] == "https://monitor.example.com:18081/"
    assert urls["netdisco"] == "https://monitor.example.com:15000/"
    assert urls["oxidized"] == "https://monitor.example.com:18888/"
    assert urls["netbox"] == "https://monitor.example.com:18444/"
    assert all(row["status"] == "up" for row in body["apps"])
    assert public_base("bad host", "443") == ""
    assert "device-secret" not in json.dumps(body)


def _settings(tmp_path: Path) -> Settings:
    secret = tmp_path / "netbox.token"
    secret.write_text("super-secret-token\n", encoding="utf-8")
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
    )


def _netbox(request: httpx.Request) -> httpx.Response:
    if request.url.host.startswith("netbox") and request.url.path.startswith("/api/dcim/devices"):
        return httpx.Response(200, json={"count": 1, "next": None, "results": [{
            "id": 10,
            "name": "core-1",
            "serial": "",
            "role": {"name": "Core", "slug": "core-switch"},
            "site": {"id": 1, "name": "Rotterdam", "slug": "rotterdam"},
            "device_type": {"model": "C9500", "manufacturer": {"name": "Cisco"}},
            "primary_ip4": {"address": "10.1.0.1/32"},
            "platform": {"name": "IOS-XE"},
        }]})
    if request.url.host.startswith("netbox"):
        return httpx.Response(200, json={"count": 0, "next": None, "results": []})
    return httpx.Response(200, text="ok")


@pytest.fixture()
def cli_app(tmp_path, monkeypatch):
    monkeypatch.setenv("IE_CONFIG_SCHEDULER", "0")
    monkeypatch.setenv("COOKIE_SECURE", "0")
    calls = []

    def fake_run(self, host, username, password, prep, command, timeout):
        calls.append({"host": host, "username": username, "command": command, "prep": list(prep)})
        assert password == "device-secret"
        return "Cisco IOS Software, version is shown"

    monkeypatch.setattr("ie_config.device_cli.ParamikoRunner.run", fake_run)
    settings = _settings(tmp_path)
    http = httpx.Client(transport=httpx.MockTransport(_netbox))
    fleet = FleetService(settings, client=http, now=lambda: 1_700_000_000)
    app = create_app(settings, fleet=fleet)
    client = TestClient(app)
    client.post(
        "/internal/bootstrap-admin",
        headers={"Authorization": "Bearer setup-token-value"},
        json={"email": "admin@example.com", "password": "Adminpass1234"},
    )
    login = client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "Adminpass1234"})
    assert login.status_code == 200, login.text
    return {"client": client, "csrf": login.json()["csrfToken"], "calls": calls, "settings": settings, "app": app}


def test_cli_requires_credentials_then_runs_only_the_allowlist(cli_app):
    client = cli_app["client"]
    csrf = cli_app["csrf"]
    anonymous = TestClient(cli_app["app"])
    assert anonymous.get("/api/v1/devices/10/cli").status_code == 401
    assert anonymous.get("/api/v1/apps/launcher").status_code == 401

    catalog = client.get("/api/v1/devices/10/cli")
    assert catalog.status_code == 200, catalog.text
    body = catalog.json()
    assert body["credentialsConfigured"] is False
    assert "CLI credentials are not set" in body["message"]
    assert any(row["command"] == "show version" for row in body["commands"])

    missing = client.post("/api/v1/devices/10/cli", headers={"X-CSRF-Token": csrf}, json={"command": "show version"})
    assert missing.status_code == 409
    assert missing.json()["error"]["code"] == "credentials_not_configured"
    assert "CLI credentials are not set" in missing.json()["error"]["message"]
    assert cli_app["calls"] == []

    saved = client.put(
        "/api/v1/devices/10/cli/credentials",
        headers={"X-CSRF-Token": csrf},
        json={"username": "ops", "password": "device-secret"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"ok": True, "configured": True}
    assert "device-secret" not in saved.text
    stored = Path(cli_app["settings"].device_cli_secret_dir) / "10.json"
    assert stored.stat().st_mode & 0o777 == 0o600

    ran = client.post("/api/v1/devices/10/cli", headers={"X-CSRF-Token": csrf}, json={"command": "show version"})
    assert ran.status_code == 200, ran.text
    assert ran.json()["output"].startswith("Cisco IOS Software")
    assert "device-secret" not in ran.text
    assert cli_app["calls"][0]["command"] == "show version"
    assert cli_app["calls"][0]["prep"] == ["terminal length 0"]
    assert cli_app["calls"][0]["host"] == "10.1.0.1"

    blocked = client.post("/api/v1/devices/10/cli", headers={"X-CSRF-Token": csrf}, json={"command": "configure terminal"})
    assert blocked.status_code == 400
    assert cli_app["calls"] == [cli_app["calls"][0]]

    with cli_app["app"].state.sf() as db:
        rows = db.query(AuditRow).filter(AuditRow.action == "device-cli").all()
        blob = " ".join((row.detail or "") + (row.comment or "") for row in rows)
    assert "device-secret" not in blob
    assert any(row.detail == "show version" and row.result == "ok" for row in rows)
    assert any(row.result == "credentials-not-configured" for row in rows)
