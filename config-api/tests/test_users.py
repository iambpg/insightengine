"""User directory: roles, the built-in admin, the last administrator, and password hashing."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from ie_config.app import create_app
from ie_config.auth import hash_password, verify_password
from ie_config.db import make_engine, make_session_factory
from ie_config.settings import Settings
from ie_config.users_migrate import ensure_user_schema


class _Reload(BaseHTTPRequestHandler):
    def do_POST(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, fmt, *args):
        return


@pytest.fixture()
def client(tmp_path, monkeypatch):
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
    actions: []
  - id: caddy
    name: Caddy
    description: proxy
    sensitive: true
    container: caddy-test
    files:
      - {id: Caddyfile, path: config/caddy/Caddyfile, label: Caddy, language: caddyfile, editable: true, validator: text}
    actions: []
""",
        encoding="utf-8",
    )
    cfg = tmp_path / "config" / "prometheus"
    cfg.mkdir(parents=True)
    (cfg / "prometheus.yml").write_text("scrape_configs: []\n", encoding="utf-8")
    (tmp_path / "config" / "caddy").mkdir()
    (tmp_path / "config" / "caddy" / "Caddyfile").write_text("http://localhost {\n  respond ok\n}\n", encoding="utf-8")
    token = tmp_path / "setup-token"
    token.write_text("setup-token-value", encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Reload)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("IE_CONFIG_SCHEDULER", "0")
    settings = Settings(
        config_root=str(tmp_path),
        apps_file=str(apps),
        database_url="sqlite:///" + str(tmp_path / "ie.db"),
        history_dir=str(tmp_path / "history"),
        cookie_secure=False,
        cookie_name="ie_session",
        setup_token_file=str(token),
        client_slug="test",
        public_host="localhost",
        docker_proxy_url="http://127.0.0.1:9",
        scheduler=False,
        netbox_url="http://127.0.0.1:9",
        netbox_token_file=str(tmp_path / "missing-token"),
        netdisco_database_url="",
        netdisco_out_dir=str(tmp_path / "nd"),
        mib_dir=str(tmp_path / "mibs"),
        candidate_dir=str(tmp_path / "cand"),
        generator_bin="/usr/local/bin/generator-missing",
    )
    app = create_app(settings)
    test_client = TestClient(app)
    yield test_client
    server.shutdown()


def _bootstrap(client: TestClient, email="admin@example.com", password="Adminpass1234"):
    response = client.post(
        "/internal/bootstrap-admin",
        headers={"Authorization": "Bearer setup-token-value"},
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text


def _login(client: TestClient, email="admin@example.com", password="Adminpass1234"):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["csrfToken"]


def _headers(csrf: str) -> dict:
    return {"X-CSRF-Token": csrf}


def test_migration_keeps_the_existing_admin_password(tmp_path):
    engine = make_engine("sqlite:///" + str(tmp_path / "old.db"))
    original = "$argon2id$v=19$m=19456,t=2,p=1$preservedhashvalue"
    with engine.begin() as conn:
        conn.execute(text(
            """
            CREATE TABLE users (
              id INTEGER PRIMARY KEY,
              email VARCHAR(320) NOT NULL,
              password_hash TEXT NOT NULL,
              role VARCHAR(32) NOT NULL,
              failed_attempts INTEGER,
              locked_until TIMESTAMP,
              created_at TIMESTAMP
            )
            """
        ))
        conn.execute(
            text(
                "INSERT INTO users (email, password_hash, role, failed_attempts) "
                "VALUES ('kept@example.com', :password_hash, 'Administrator', 0)"
            ),
            {"password_hash": original},
        )
    ensure_user_schema(engine)
    with engine.begin() as conn:
        row = conn.execute(text("SELECT username, password_hash, role, builtin, email FROM users")).mappings().one()
        assert row["password_hash"] == original
        assert row["email"] == "kept@example.com"
        assert row["role"] == "Administrator"
        assert row["username"] == "admin"
        assert row["builtin"] == 1
    for statement in (
        "UPDATE users SET role = 'Operator' WHERE username = 'admin'",
        "UPDATE users SET status = 'disabled' WHERE username = 'admin'",
        "DELETE FROM users WHERE username = 'admin'",
    ):
        with pytest.raises(Exception, match="builtin admin"):
            with engine.begin() as conn:
                conn.execute(text(statement))


def test_builtin_admin_cannot_be_removed_and_login_still_works(client):
    password = "Adminpass1234"
    _bootstrap(client, password=password)
    csrf = _login(client, "admin", password)
    me = client.get("/api/v1/auth/me").json()
    assert me["role"] == "Administrator"
    assert me["username"] == "admin"
    assert me["email"] == "admin@example.com"
    listed = client.get("/api/v1/auth/users").json()
    assert listed[0]["username"] == "admin"
    assert listed[0]["builtin"] is True
    assert "password" not in listed[0]
    assert password not in client.get("/api/v1/auth/users").text
    admin_id = listed[0]["id"]
    for method, path, body in (
        ("patch", "/api/v1/auth/users/%s" % admin_id, {"role": "Operator"}),
        ("patch", "/api/v1/auth/users/%s" % admin_id, {"role": "Read-only"}),
        ("post", "/api/v1/auth/users/%s/disable" % admin_id, {}),
    ):
        response = getattr(client, method)(path, headers=_headers(csrf), json=body)
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "protected_admin"
    removed = client.delete("/api/v1/auth/users/%s" % admin_id, headers=_headers(csrf))
    assert removed.status_code == 403
    assert removed.json()["error"]["code"] == "self_delete"
    renamed = client.patch(
        "/api/v1/auth/users/%s" % admin_id,
        headers=_headers(csrf),
        json={"displayName": "Platform admin", "email": "kept@example.com"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["role"] == "Administrator"
    assert _login(client, "kept@example.com", password)


def test_last_admin_and_self_delete(client):
    _bootstrap(client)
    csrf = _login(client)
    created = client.post(
        "/api/v1/auth/users",
        headers=_headers(csrf),
        json={
            "username": "lead",
            "displayName": "Lead Admin",
            "email": "lead@example.com",
            "role": "Admin",
            "password": "Leadpass12345",
            "forceChange": False,
        },
    )
    assert created.status_code == 200, created.text
    lead_id = created.json()["id"]
    assert created.json()["role"] == "Administrator"
    client.post("/api/v1/auth/logout", headers=_headers(csrf))
    lead = _login(client, "lead@example.com", "Leadpass12345")
    builtin_id = next(row["id"] for row in client.get("/api/v1/auth/users").json() if row["username"] == "admin")
    blocked = client.delete("/api/v1/auth/users/%s" % builtin_id, headers=_headers(lead))
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "protected_admin"
    denied = client.delete("/api/v1/auth/users/%s" % lead_id, headers=_headers(lead))
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "self_delete"
    client.post("/api/v1/auth/logout", headers=_headers(lead))
    csrf = _login(client)
    # The built-in account is the other administrator, so this one can be demoted.
    demoted = client.patch(
        "/api/v1/auth/users/%s" % lead_id,
        headers=_headers(csrf),
        json={"role": "Viewer"},
    )
    assert demoted.status_code == 200, demoted.text
    assert demoted.json()["role"] == "Read-only"
    # A second non-built-in administrator cannot be removed when they are the only
    # extra admin and we then remove every other non-protected path: promote them
    # back, disable the check by having only the built-in left, and reject a
    # direct demotion of the last *additional* admin once the built-in is the
    # sole survivor. Promote an operator to admin and demote them again.
    again = client.patch(
        "/api/v1/auth/users/%s" % lead_id,
        headers=_headers(csrf),
        json={"role": "Administrator"},
    )
    assert again.status_code == 200, again.text
    # Insert a directory whose only administrators are not the built-in name by
    # demoting nothing else: two admins exist, demoting one leaves one, which is allowed.
    left = client.patch(
        "/api/v1/auth/users/%s" % lead_id,
        headers=_headers(csrf),
        json={"role": "Operator"},
    )
    assert left.status_code == 200, left.text


def test_last_remaining_admin_is_refused(tmp_path):
    """Demoting an administrator is refused when nobody else would still be an active admin."""
    url = "sqlite:///" + str(tmp_path / "ie.db")
    factory, _engine = make_session_factory(url)
    from ie_config.auth import Auth
    from ie_config.db import User

    settings = Settings(
        config_root=str(tmp_path),
        apps_file=str(tmp_path / "apps.yml"),
        database_url=url,
        history_dir=str(tmp_path / "history"),
        cookie_secure=False,
        cookie_name="ie_session",
        setup_token_file=str(tmp_path / "token"),
        client_slug="test",
        public_host="localhost",
        docker_proxy_url="http://127.0.0.1:9",
        scheduler=False,
        netbox_url="http://127.0.0.1:9",
        netbox_token_file=str(tmp_path / "missing"),
        netdisco_database_url="",
        netdisco_out_dir=str(tmp_path / "nd"),
        mib_dir=str(tmp_path / "mibs"),
        candidate_dir=str(tmp_path / "cand"),
        generator_bin="missing",
    )
    auth = Auth(factory, settings)
    with factory() as db:
        db.add(User(
            email="one@example.com", password_hash=hash_password("Onepass123456"),
            role="Administrator", username="one", display_name="One", status="active", builtin=0,
        ))
        db.add(User(
            email="two@example.com", password_hash=hash_password("Twopass123456"),
            role="Administrator", username="two", display_name="Two", status="active", builtin=0,
        ))
        db.commit()
        rows = list(db.scalars(select(User).order_by(User.id)))
        ids = [(row.id, row.username) for row in rows]
    assert [name for _id, name in ids] == ["one", "two"]
    actor = type("A", (), {"id": ids[0][0], "email": "one@example.com", "role": "Administrator"})()
    changed = auth.update_user(actor, ids[1][0], {"role": "Viewer"}, "test")
    assert changed["role"] == "Read-only"
    with pytest.raises(Exception) as exc:
        auth.update_user(actor, ids[0][0], {"role": "Operator"}, "test")
    assert exc.value.code == "last_admin"
    with pytest.raises(Exception) as disabled:
        auth.set_status(actor, ids[0][0], "disabled", "test")
    assert disabled.value.code == "last_admin"


def test_roles_are_enforced_and_passwords_are_hashed(client):
    password = "Adminpass1234"
    _bootstrap(client, password=password)
    csrf = _login(client)
    factory, _engine = make_session_factory(client.app.state.settings.database_url)
    with factory() as db:
        from ie_config.db import User
        from sqlalchemy import select
        admin = db.scalar(select(User).where(User.username == "admin"))
        assert admin.password_hash.startswith("$argon2")
        assert verify_password(password, admin.password_hash)
        assert password not in admin.password_hash

    generated = client.post(
        "/api/v1/auth/users",
        headers=_headers(csrf),
        json={
            "username": "ops",
            "displayName": "Ops User",
            "email": "ops@example.com",
            "role": "Operator",
            "generate": True,
            "forceChange": True,
        },
    )
    assert generated.status_code == 200, generated.text
    otp = generated.json()["oneTimePassword"]
    assert otp and otp not in generated.json()["email"]
    viewer = client.post(
        "/api/v1/auth/users",
        headers=_headers(csrf),
        json={
            "username": "view",
            "displayName": "View User",
            "email": "view@example.com",
            "role": "Viewer",
            "password": "Viewerpass123",
            "forceChange": False,
        },
    )
    assert viewer.status_code == 200, viewer.text
    assert viewer.json()["role"] == "Read-only"
    assert "password" not in viewer.json()
    audit = client.get("/api/v1/auth/users/audit").json()["entries"]
    blob = str(audit)
    assert password not in blob
    assert otp not in blob
    assert any(row["action"] == "user-create" for row in audit)

    client.post("/api/v1/auth/logout", headers=_headers(csrf))
    op = _login(client, "ops", otp)
    assert client.get("/api/v1/auth/me").json()["mustChangePassword"] is True
    blocked = client.get("/api/v1/settings/apps")
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "password_change_required"
    changed = client.post(
        "/api/v1/auth/change-password",
        headers=_headers(op),
        json={"currentPassword": otp, "newPassword": "Operatorpass12"},
    )
    assert changed.status_code == 200, changed.text
    assert client.get("/api/v1/auth/me").json()["mustChangePassword"] is False
    assert client.get("/api/v1/settings/apps").status_code == 403
    assert client.get("/api/v1/settings/vault").status_code == 403
    assert client.get("/api/v1/auth/users").status_code == 403
    assert client.get("/api/v1/discovery/unapproved").status_code == 200
    preview = client.post("/api/v1/netbridge/stacks/preview", headers=_headers(op), json={})
    assert preview.status_code != 403
    client.post("/api/v1/auth/logout", headers=_headers(op))

    view = _login(client, "view@example.com", "Viewerpass123")
    # NetBox is not running in this fixture, so a read may be 200 or an upstream 502.
    # Either way it must not be a role rejection.
    assert client.get("/api/v1/devices").status_code != 403
    for method, path in (
        ("get", "/api/v1/auth/users"),
        ("get", "/api/v1/settings/apps"),
        ("get", "/api/v1/settings/vault"),
        ("get", "/api/v1/discovery/unapproved"),
    ):
        response = getattr(client, method)(path, headers=_headers(view))
        assert response.status_code == 403, path
    acked = client.post("/api/v1/alerts/acknowledge", headers=_headers(view), json={"ids": ["x"]})
    assert acked.status_code == 403
    wrote = client.post("/api/v1/netbridge/stacks/preview", headers=_headers(view), json={})
    assert wrote.status_code == 403
    client.post("/api/v1/auth/logout", headers=_headers(view))

    csrf = _login(client)
    ops_id = next(row["id"] for row in client.get("/api/v1/auth/users").json() if row["username"] == "ops")
    disabled = client.post("/api/v1/auth/users/%s/disable" % ops_id, headers=_headers(csrf))
    assert disabled.status_code == 200, disabled.text
    refused = client.post("/api/v1/auth/login", json={"email": "ops@example.com", "password": "Operatorpass12"})
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "disabled"
    enabled = client.post("/api/v1/auth/users/%s/enable" % ops_id, headers=_headers(csrf))
    assert enabled.status_code == 200
    assert _login(client, "ops@example.com", "Operatorpass12")


def test_operator_ack_is_not_forbidden(client):
    _bootstrap(client)
    csrf = _login(client)
    client.post(
        "/api/v1/auth/users",
        headers=_headers(csrf),
        json={
            "username": "ops2",
            "displayName": "Ops Two",
            "email": "ops2@example.com",
            "role": "Operator",
            "password": "Operatorpass12",
            "forceChange": False,
        },
    )
    client.post("/api/v1/auth/logout", headers=_headers(csrf))
    op = _login(client, "ops2@example.com", "Operatorpass12")
    response = client.post("/api/v1/alerts/acknowledge", headers=_headers(op), json={"ids": ["missing"]})
    assert response.status_code != 403
