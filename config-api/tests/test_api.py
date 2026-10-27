"""ie-config unit tests. SQLite file, fake validator binary, fake reload HTTP server. No Docker."""

from __future__ import annotations

import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ie_config.app import create_app
from ie_config.discovery import guess_device, select_prefixes, valid_cidr
from ie_config.masking import mask_text, restore_secrets
from ie_config.registry import FileSpec, Registry, load_registry
from ie_config.settings import Settings
from ie_config.snmpgen import safe_mib_name, save_mib

ROOT = Path(__file__).resolve().parents[2]
APPS = ROOT / "config-api" / "apps.yml"
REQUIRED = {
    "prometheus", "alertmanager", "snmp-exporter", "snmp-generator", "blackbox-exporter",
    "telegraf", "grafana", "caddy", "netbox", "activepieces", "loki", "promtail-or-syslog",
    "oxidized", "trapd", "netdisco", "postgres", "host",
}


class ReloadHandler(BaseHTTPRequestHandler):
    seen = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        ReloadHandler.seen.append((self.path, body[:40]))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, fmt, *args):
        return


@pytest.fixture()
def world(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    (cfg / "prometheus").mkdir(parents=True)
    (cfg / "caddy").mkdir()
    prom = cfg / "prometheus" / "prometheus.yml"
    prom.write_text("scrape_configs: []\n", encoding="utf-8")
    (cfg / "caddy" / "Caddyfile").write_text("http://localhost {\n  respond ok\n}\n", encoding="utf-8")
    secret = tmp_path / "secrets" / "prometheus"
    secret.mkdir(parents=True)
    (secret / "netbox.token").write_text("super-secret-token\n", encoding="utf-8")
    apps = tmp_path / "apps.yml"
    apps.write_text(
        """
version: 1
apps:
  - id: prometheus
    name: Prometheus
    description: metrics
    sensitive: false
    container: prometheus-test
    files:
      - {id: prometheus.yml, path: config/prometheus/prometheus.yml, label: Prom, language: yaml, editable: true, validator: yaml}
      - {id: netbox.token, path: secrets/prometheus/netbox.token, label: Token, language: text, editable: false, secret_file: true}
    actions:
      - {id: reload, label: Reload, kind: reload, roles: [Administrator, Engineer], http: [{method: POST, url: "http://127.0.0.1:__PORT__/-/reload"}]}
      - {id: restart, label: Restart, kind: restart, dangerous: true, roles: [Administrator], containers: [prometheus-test]}
  - id: caddy
    name: Caddy
    description: proxy
    sensitive: true
    container: caddy-test
    files:
      - {id: Caddyfile, path: config/caddy/Caddyfile, label: Caddy, language: caddyfile, editable: true, validator: text}
    actions:
      - {id: reload, label: Reload, kind: reload, dangerous: true, roles: [Administrator]}
      - {id: restart, label: Restart, kind: restart, dangerous: true, roles: [Administrator], containers: [caddy-test]}
""",
        encoding="utf-8",
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), ReloadHandler)
    port = server.server_address[1]
    apps.write_text(apps.read_text(encoding="utf-8").replace("__PORT__", str(port)), encoding="utf-8")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    token = tmp_path / "setup-token"
    token.write_text("setup-token-value", encoding="utf-8")
    db = tmp_path / "ie.db"
    monkeypatch.setenv("IE_CONFIG_SCHEDULER", "0")
    monkeypatch.setenv("COOKIE_SECURE", "0")
    settings = Settings(
        config_root=str(tmp_path),
        apps_file=str(apps),
        database_url="sqlite:///" + str(db),
        history_dir=str(tmp_path / "history"),
        cookie_secure=False,
        cookie_name="ie_session",
        setup_token_file=str(token),
        client_slug="test",
        public_host="localhost",
        docker_proxy_url="http://127.0.0.1:9",
        scheduler=False,
        netbox_url="http://127.0.0.1:9",
        netbox_token_file=str(secret / "netbox.token"),
        netdisco_database_url="",
        netdisco_out_dir=str(tmp_path / "nd"),
        mib_dir=str(tmp_path / "mibs"),
        candidate_dir=str(tmp_path / "cand"),
        generator_bin="/usr/local/bin/generator-missing",
    )
    app = create_app(settings)
    client = TestClient(app)
    yield {"client": client, "root": tmp_path, "prom": prom, "port": port}
    server.shutdown()


def _bootstrap(client: TestClient, email="admin@example.com", password="Adminpass1234"):
    r = client.post(
        "/internal/bootstrap-admin",
        headers={"Authorization": "Bearer setup-token-value"},
        json={"email": email, "password": password},
    )
    assert r.status_code == 200, r.text


def _login(client: TestClient, email="admin@example.com", password="Adminpass1234"):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["csrfToken"]


def test_registry_rejects_traversal(tmp_path):
    reg = Registry([], str(tmp_path))
    with pytest.raises(ValueError):
        reg.resolve(FileSpec("x", "../etc/passwd", "", "text", False, False, "", "text", False))
    with pytest.raises(ValueError):
        reg.resolve(FileSpec("x", "/etc/passwd", "", "text", False, False, "", "text", False))
    with pytest.raises(ValueError):
        reg.resolve(FileSpec("x", "config/../../etc/passwd", "", "text", False, False, "", "text", False))


def test_real_apps_registry():
    reg = load_registry(str(APPS), str(ROOT), env={})
    ids = {a.id for a in reg.apps}
    assert REQUIRED <= ids
    seen = set()
    for app in reg.apps:
        for f in app.files:
            assert ".." not in f.path
            assert not f.path.startswith("/")
            key = app.id + "/" + f.id
            assert key not in seen
            seen.add(key)
            reg.resolve(f)


def test_mask_and_restore():
    raw = "password: hunter2\ncommunity: ${SNMP_V2_COMMUNITY}\npassword: second-one\n"
    masked, keys = mask_text(raw)
    assert "hunter2" not in masked
    assert "second-one" not in masked
    assert "${SNMP_V2_COMMUNITY}" in masked
    assert "__SECRET__:password" in masked
    assert "__SECRET__:password#2" in masked
    assert "password" in keys and "password#2" in keys
    assert restore_secrets(masked, raw) == raw


def test_bootstrap_csrf_and_roles(world):
    client = world["client"]
    assert client.get("/healthz").json()["ok"] is True
    assert client.post("/internal/bootstrap-admin", json={"email": "a@b.co", "password": "Adminpass1234"}).status_code == 401
    _bootstrap(client)
    assert client.post(
        "/internal/bootstrap-admin",
        headers={"Authorization": "Bearer setup-token-value"},
        json={"email": "other@example.com", "password": "Adminpass1234"},
    ).status_code == 409
    csrf = _login(client)
    assert client.get("/api/v1/settings/apps").status_code == 200
    # write without CSRF
    r = client.put(
        "/api/v1/settings/apps/prometheus/files/prometheus.yml",
        json={"content": "scrape_configs: []\n", "etag": "x"},
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf"
    r = client.post(
        "/api/v1/auth/users",
        headers={"X-CSRF-Token": csrf},
        json={"email": "eng@example.com", "password": "Engineerpass1", "role": "Engineer"},
    )
    assert r.status_code == 200
    r = client.post(
        "/api/v1/auth/users",
        headers={"X-CSRF-Token": csrf},
        json={"email": "op@example.com", "password": "Operatorpass1", "role": "Operator"},
    )
    assert r.status_code == 200
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    op = _login(client, "op@example.com", "Operatorpass1")
    denied = client.get("/api/v1/settings/apps")
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "forbidden"
    denied = client.get("/api/v1/discovery/unapproved")
    assert denied.status_code == 403
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": op})
    eng = _login(client, "eng@example.com", "Engineerpass1")
    assert client.get("/api/v1/settings/apps/caddy/files/Caddyfile").status_code == 200
    etag = client.get("/api/v1/settings/apps/caddy/files/Caddyfile").json()["etag"]
    blocked = client.put(
        "/api/v1/settings/apps/caddy/files/Caddyfile",
        headers={"X-CSRF-Token": eng},
        json={"content": "http://localhost {\n  respond ok\n}\n", "etag": etag},
    )
    assert blocked.status_code == 403
    # restart is administrator only
    restarted = client.post(
        "/api/v1/settings/apps/prometheus/actions/restart",
        headers={"X-CSRF-Token": eng},
        json={},
    )
    assert restarted.status_code == 403


def test_secret_file_hidden_and_traversal(world):
    client = world["client"]
    _bootstrap(client)
    csrf = _login(client)
    hidden = client.get("/api/v1/settings/apps/prometheus/files/netbox.token")
    assert hidden.status_code == 403 and hidden.json()["error"]["code"] == "secret_file"
    assert "super-secret-token" not in hidden.text
    missing = client.get("/api/v1/settings/apps/prometheus/files/..%2F..%2Fetc%2Fpasswd")
    assert missing.status_code == 404
    apps = client.get("/api/v1/settings/apps").json()
    blob = str(apps)
    assert "super-secret-token" not in blob
    assert "password" not in blob


def test_etag_conflict_validation_audit_and_reload(world):
    client = world["client"]
    _bootstrap(client)
    csrf = _login(client)
    ReloadHandler.seen.clear()
    got = client.get("/api/v1/settings/apps/prometheus/files/prometheus.yml").json()
    original = world["prom"].read_text(encoding="utf-8")
    bad = client.put(
        "/api/v1/settings/apps/prometheus/files/prometheus.yml",
        headers={"X-CSRF-Token": csrf},
        json={"content": "a: [\n", "etag": got["etag"], "comment": "bad"},
    )
    assert bad.status_code == 422
    assert bad.json()["ok"] is False
    assert world["prom"].read_text(encoding="utf-8") == original
    stale = client.put(
        "/api/v1/settings/apps/prometheus/files/prometheus.yml",
        headers={"X-CSRF-Token": csrf},
        json={"content": "scrape_configs: []\njobs: []\n", "etag": "deadbeef", "comment": "stale"},
    )
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "etag_conflict"
    assert world["prom"].read_text(encoding="utf-8") == original
    saved = client.put(
        "/api/v1/settings/apps/prometheus/files/prometheus.yml",
        headers={"X-CSRF-Token": csrf},
        json={"content": "scrape_configs:\n  - job_name: demo\n", "etag": got["etag"], "comment": "add demo", "apply": True},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["applied"] is True
    assert "job_name: demo" in world["prom"].read_text(encoding="utf-8")
    assert ReloadHandler.seen and ReloadHandler.seen[0][0] == "/-/reload"
    audit = client.get("/api/v1/settings/audit").json()
    actions = [e["action"] for e in audit["entries"]]
    assert "save" in actions
    assert any(e["action"] == "save" and e["result"] == "ok" and e["comment"] == "add demo" for e in audit["entries"])
    # secret restore: a masked placeholder is written back as the original token
    secret_file = world["root"] / "config" / "prometheus" / "prometheus.yml"
    secret_file.write_text("password: hunter2\nscrape_configs: []\n", encoding="utf-8")
    body = client.get("/api/v1/settings/apps/prometheus/files/prometheus.yml").json()
    assert "hunter2" not in body["content"]
    assert "password" in body["maskedKeys"]
    restored = client.put(
        "/api/v1/settings/apps/prometheus/files/prometheus.yml",
        headers={"X-CSRF-Token": csrf},
        json={"content": body["content"], "etag": body["etag"], "comment": "keep secret"},
    )
    assert restored.status_code == 200, restored.text
    assert "password: hunter2" in secret_file.read_text(encoding="utf-8")


def test_lockout(world):
    client = world["client"]
    _bootstrap(client)
    for _ in range(5):
        r = client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "wrong-password-1"})
        assert r.status_code == 401
    locked = client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "Adminpass1234"})
    assert locked.status_code == 429 and locked.json()["error"]["code"] == "locked"


def test_discovery_selection_and_mib_names(tmp_path):
    prefixes = [
        {"prefix": "203.0.113.0/24", "status": {"value": "active"}, "tags": [{"slug": "ie-scan"}]},
        {"prefix": "198.51.100.0/24", "status": "active", "tags": []},
        {"prefix": "192.0.2.0/24", "status": "active", "custom_fields": {"ie_scan": True}},
        {"prefix": "not a prefix", "status": "active", "tags": [{"slug": "ie-scan"}]},
    ]
    assert select_prefixes(prefixes, {"prefix_selector": "tag", "tag": "ie-scan"}) == ["203.0.113.0/24"]
    assert "192.0.2.0/24" in select_prefixes(prefixes, {"prefix_selector": "custom_field"})
    assert len(select_prefixes(prefixes, {"scan_all_active_prefixes": True})) == 3
    assert valid_cidr("203.0.113.0/24")
    assert not valid_cidr("10.0.0.0/99")
    guess = guess_device(
        "1.3.6.1.4.1.9.1.1",
        "Cisco IOS Software, C9300",
        {"default_role": "access-switch", "prefixes": [
            {"oid": "1.3.6.1.4.1.9", "manufacturer": "Cisco", "manufacturer_slug": "cisco", "platform": "ios", "role": "access-switch"},
        ], "descr_patterns": []},
    )
    assert guess["manufacturer_slug"] == "cisco"
    assert guess["role"] == "access-switch"
    assert safe_mib_name("../x.mib") is None
    assert safe_mib_name("CISCO-SMI.mib") == "CISCO-SMI.mib"
    with pytest.raises(ValueError):
        save_mib(str(tmp_path), "ok.mib", b"x" * 10, file_max=4, total_max=20)


def test_fake_promtool_does_not_write_live_file(tmp_path, monkeypatch):
    binary = tmp_path / "promtool"
    binary.write_text("#!/bin/sh\ngrep -q INVALID \"$3\" && exit 1\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.setenv("PROMTOOL_BIN", str(binary))
    from ie_config.validators import validate_content
    live = tmp_path / "live.yml"
    live.write_text("groups: []\n", encoding="utf-8")
    bad = validate_content("promtool-rules", "yaml", "groups: []\n# INVALID\n")
    assert bad["ok"] is False
    assert "promtool" in bad["tool"]
    assert live.read_text(encoding="utf-8") == "groups: []\n"
    good = validate_content("promtool-rules", "yaml", "groups: []\n")
    assert good["ok"] is True
