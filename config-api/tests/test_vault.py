"""Vault is admin-only. The list is masked. Reveal needs the current password."""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from ie_config.app import create_app
from ie_config.apps_launcher import build_catalog
from ie_config.auth import token_hash
from ie_config.db import AuditRow, utcnow
from ie_config.settings import Settings
from ie_config.vault import is_secret_key, list_view, parse_env, too_many_failures

SECRET = "vault-secret-db-value"
TOKEN = "vault-secret-token-value"
HASH = "$2b$12$examplehashvalue"
PASSWORD = "Adminpass1234"


def test_parse_unquotes_and_masks_secret_names():
    text = "\n".join([
        "# comment",
        "CLIENT_NAME='Acme'      # the client",
        "PORT_NETBOX=8092                # public",
        "ADMIN_BASIC_HASH='%s'" % HASH,
        "NETBOX_DB_PASSWORD='%s'" % SECRET,
        "NETBOX_DB_PASSWORD='replaced'",
        "export SNMP_V2_COMMUNITY='community-value'",
        "GRAFANA_ADMIN_USER=admin",
        "EMPTY_SECRET_KEY=",
        "",
    ])
    pairs = dict(parse_env(text))
    assert pairs["CLIENT_NAME"] == "Acme"
    assert pairs["PORT_NETBOX"] == "8092"
    assert pairs["ADMIN_BASIC_HASH"] == HASH
    assert pairs["NETBOX_DB_PASSWORD"] == "replaced"
    assert pairs["SNMP_V2_COMMUNITY"] == "community-value"
    assert pairs["GRAFANA_ADMIN_USER"] == "admin"
    assert pairs["EMPTY_SECRET_KEY"] == ""
    assert is_secret_key("NETBOX_DB_PASSWORD")
    assert is_secret_key("ADMIN_BASIC_HASH")
    assert is_secret_key("SNMP_V2_COMMUNITY")
    assert is_secret_key("GRAFANA_SECRET_KEY")
    assert is_secret_key("AP_ENCRYPTION_KEY")
    assert is_secret_key("NETBOX_SUPERUSER_API_TOKEN")
    assert not is_secret_key("GRAFANA_ADMIN_USER")
    assert not is_secret_key("PORT_NETBOX")
    assert not is_secret_key("SNMP_V3_USERNAME")
    view = list_view(list(pairs.items()), "monitor.example.com")
    flat = json.dumps(view)
    assert SECRET not in flat
    assert HASH not in flat
    assert "community-value" not in flat
    assert "replaced" not in flat
    netbox = next(group for group in view["groups"] if group["id"] == "netbox")
    assert netbox["endpoints"][0]["url"] == "https://monitor.example.com:8092/"
    assert netbox["endpoints"][0]["port"] == 8092
    password = next(item for item in netbox["entries"] if item["key"] == "NETBOX_DB_PASSWORD")
    assert password["secret"] is True and "value" not in password
    user = next(item for item in view["groups"] if item["id"] == "grafana")
    visible = next(item for item in user["entries"] if item["key"] == "GRAFANA_ADMIN_USER")
    assert visible["value"] == "admin"
    basic = next(item for item in view["groups"] if item["id"] == "prometheus-alertmanager")
    assert any(item["key"] == "ADMIN_BASIC_HASH" and item["secret"] for item in basic["entries"])
    assert any(item["url"] == "https://monitor.example.com:8086/" for item in basic["endpoints"])


def test_failure_window_blocks_the_ninth_attempt():
    bucket: dict = {}
    for _ in range(8):
        assert too_many_failures(bucket, "1", 1000.0) is False
        bucket.setdefault("1", []).append(1000.0)
    assert too_many_failures(bucket, "1", 1000.0) is True
    assert too_many_failures(bucket, "1", 1061.0) is False


def test_launcher_defaults_follow_the_firewall_ports(monkeypatch):
    for name in ("PORT_HTTPS", "PORT_NETBOX", "PORT_ALERTMANAGER", "PORT_HTTP", "PORT_GRAFANA", "PORT_PROMETHEUS"):
        monkeypatch.delenv(name, raising=False)
    import httpx
    client = httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(200, text="ok")))
    urls = {row["id"]: row["url"] for row in build_catalog("monitor.example.com", "Administrator", client)["apps"]}
    assert urls["ui"] == "https://monitor.example.com/"
    assert urls["netbox"] == "https://monitor.example.com:8092/"
    assert urls["alertmanager"] == "https://monitor.example.com:8086/"
    assert urls["grafana"] == "https://monitor.example.com:3000/"
    assert urls["prometheus"] == "https://monitor.example.com:9090/"


def _settings(tmp_path: Path) -> Settings:
    secret = tmp_path / "netbox.token"
    secret.write_text("super-secret-token\n", encoding="utf-8")
    (tmp_path / "setup-token").write_text("setup-token-value", encoding="utf-8")
    (tmp_path / "apps.yml").write_text("version: 1\napps: []\n", encoding="utf-8")
    env = tmp_path / ".env"
    env.write_text(
        "\n".join([
            "PUBLIC_HOST='monitor.example.com'",
            "PORT_HTTP=18086",
            "PORT_HTTPS=57400",
            "PORT_NETBOX=8092",
            "PORT_ALERTMANAGER=8086",
            "PORT_PROMETHEUS=9090",
            "PORT_GRAFANA=3000",
            "GRAFANA_ADMIN_USER=admin",
            "NETBOX_SUPERUSER_NAME=admin",
            "NETBOX_DB_PASSWORD='%s'" % SECRET,
            "NETBOX_SUPERUSER_API_TOKEN='%s'" % TOKEN,
            "ADMIN_BASIC_USER=admin",
            "ADMIN_BASIC_HASH='%s'" % HASH,
            "ADMIN_BASIC_PASSWORD='basic-secret-value'",
            "SNMP_V3_USERNAME=mon-user",
            "SNMP_V3_AUTH_PASSWORD='snmp-auth-secret'",
        ]) + "\n",
        encoding="utf-8",
    )
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
        env_file=str(env),
    )


def _boot(client: TestClient) -> None:
    created = client.post(
        "/internal/bootstrap-admin",
        headers={"Authorization": "Bearer setup-token-value"},
        json={"email": "admin@example.com", "password": PASSWORD},
    )
    assert created.status_code == 200, created.text


def _login(client: TestClient, email: str, password: str) -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["csrfToken"]


def _app(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("IE_CONFIG_SCHEDULER", "0")
    monkeypatch.setenv("COOKIE_SECURE", "0")
    settings = _settings(tmp_path)
    app = create_app(settings)
    return app, TestClient(app)


def test_vault_hides_secrets_until_the_admin_reauthenticates(tmp_path, monkeypatch):
    app, client = _app(tmp_path, monkeypatch)
    _boot(client)
    csrf = _login(client, "admin@example.com", PASSWORD)
    anonymous = TestClient(app)
    assert anonymous.get("/api/v1/settings/vault").status_code == 401

    created = client.post(
        "/api/v1/auth/users",
        headers={"X-CSRF-Token": csrf},
        json={"email": "eng@example.com", "password": "Engineerpass1", "role": "Engineer"},
    )
    assert created.status_code == 200, created.text
    engineer = TestClient(app)
    eng_csrf = _login(engineer, "eng@example.com", "Engineerpass1")
    denied = engineer.get("/api/v1/settings/vault")
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "forbidden"
    assert denied.headers["cache-control"] == "no-store"
    assert SECRET not in denied.text

    listed = client.get("/api/v1/settings/vault")
    assert listed.status_code == 200, listed.text
    assert listed.headers["cache-control"] == "no-store"
    assert "no-cache" in listed.headers["pragma"]
    body = listed.json()
    assert body["readOnly"] is True
    assert body["revealSeconds"] == 300
    blob = listed.text
    for hidden in (SECRET, TOKEN, HASH, "basic-secret-value", "snmp-auth-secret"):
        assert hidden not in blob
    netbox = next(group for group in body["groups"] if group["id"] == "netbox")
    assert netbox["endpoints"][0]["url"] == "https://monitor.example.com:8092/"
    assert netbox["endpoints"][0]["portKey"] == "PORT_NETBOX"
    password_row = next(item for item in netbox["entries"] if item["key"] == "NETBOX_DB_PASSWORD")
    assert password_row == {"key": "NETBOX_DB_PASSWORD", "secret": True, "set": True}
    name_row = next(item for item in netbox["entries"] if item["key"] == "NETBOX_SUPERUSER_NAME")
    assert name_row["value"] == "admin"
    snmp = next(group for group in body["groups"] if group["id"] == "snmp")
    username = next(item for item in snmp["entries"] if item["key"] == "SNMP_V3_USERNAME")
    assert username["secret"] is False and username["value"] == "mon-user"
    https = next(group for group in body["groups"] if group["id"] == "ui-admin")
    assert any(item["port"] == 57400 and item["portKey"] == "PORT_HTTPS" for item in https["endpoints"])
    assert any(item["port"] == 18086 and item["portKey"] == "PORT_HTTP" for item in https["endpoints"])

    blocked = client.post(
        "/api/v1/settings/vault/reveal",
        headers={"X-CSRF-Token": csrf},
        json={"key": "NETBOX_DB_PASSWORD", "action": "reveal"},
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "reauth_required"
    assert blocked.headers["cache-control"] == "no-store"
    assert SECRET not in blocked.text

    logs = _LogGrab()
    root = logging.getLogger()
    previous_level = root.level
    root.setLevel(logging.DEBUG)
    root.addHandler(logs)
    try:
        wrong = client.post(
            "/api/v1/settings/vault/unlock",
            headers={"X-CSRF-Token": csrf},
            json={"password": "not-the-password"},
        )
        assert wrong.status_code == 401
        assert SECRET not in wrong.text
        assert "not-the-password" not in wrong.text
        opened = client.post(
            "/api/v1/settings/vault/unlock",
            headers={"X-CSRF-Token": csrf},
            json={"password": PASSWORD},
        )
        assert opened.status_code == 200, opened.text
        assert opened.json()["expiresIn"] == 300
        assert opened.headers["cache-control"] == "no-store"
        revealed = client.post(
            "/api/v1/settings/vault/reveal",
            headers={"X-CSRF-Token": csrf},
            json={"key": "NETBOX_DB_PASSWORD", "action": "reveal"},
        )
        assert revealed.status_code == 200, revealed.text
        assert revealed.json() == {"key": "NETBOX_DB_PASSWORD", "value": SECRET, "action": "reveal"}
        assert revealed.headers["cache-control"] == "no-store"
        copied = client.post(
            "/api/v1/settings/vault/reveal",
            headers={"X-CSRF-Token": csrf},
            json={"key": "NETBOX_SUPERUSER_API_TOKEN", "action": "copy"},
        )
        assert copied.status_code == 200, copied.text
        assert copied.json()["value"] == TOKEN
        assert copied.json()["action"] == "copy"
    finally:
        root.removeHandler(logs)
        root.setLevel(previous_level)
    logged = "\n".join(logs.messages)
    for hidden in (SECRET, TOKEN, HASH, PASSWORD, "not-the-password", "basic-secret-value", "snmp-auth-secret"):
        assert hidden not in logged

    with app.state.sf() as db:
        rows = db.query(AuditRow).all()
    dumped = json.dumps([
        {
            "user": row.user_email,
            "action": row.action,
            "file": row.file_id,
            "detail": row.detail,
            "comment": row.comment,
            "app": row.app,
            "result": row.result,
            "at": row.ts.isoformat() if row.ts else "",
        }
        for row in rows
    ])
    for hidden in (SECRET, TOKEN, HASH, PASSWORD, "not-the-password", "basic-secret-value"):
        assert hidden not in dumped
    reveals = [row for row in rows if row.action == "vault-reveal" and row.result == "ok"]
    assert len(reveals) == 1
    assert reveals[0].user_email == "admin@example.com"
    assert reveals[0].file_id == "NETBOX_DB_PASSWORD"
    assert reveals[0].ts is not None
    assert reveals[0].detail == ""
    copies = [row for row in rows if row.action == "vault-copy"]
    assert len(copies) == 1 and copies[0].file_id == "NETBOX_SUPERUSER_API_TOKEN"
    assert any(row.action == "vault-unlock" and row.result == "denied" for row in rows)
    assert any(row.action == "vault-unlock" and row.result == "ok" for row in rows)

    raw = client.cookies.get("ie_session")
    app.state.vault_sessions[token_hash(raw)] = utcnow() - timedelta(seconds=1)
    expired = client.post(
        "/api/v1/settings/vault/reveal",
        headers={"X-CSRF-Token": csrf},
        json={"key": "NETBOX_DB_PASSWORD"},
    )
    assert expired.status_code == 403
    assert expired.json()["error"]["code"] == "reauth_required"
    assert SECRET not in expired.text

    again = client.post(
        "/api/v1/settings/vault/unlock",
        headers={"X-CSRF-Token": csrf},
        json={"password": PASSWORD},
    )
    assert again.status_code == 200
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert token_hash(raw) not in app.state.vault_sessions
    engineer_reveal = engineer.post(
        "/api/v1/settings/vault/reveal",
        headers={"X-CSRF-Token": eng_csrf},
        json={"key": "NETBOX_DB_PASSWORD", "action": "reveal"},
    )
    assert engineer_reveal.status_code == 403
    assert SECRET not in engineer_reveal.text


class _LogGrab(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())
