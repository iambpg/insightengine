"""Live Netdisco discover. Skips unless the local Netdisco database from the docker test is up.

The containers are netdisco/netdisco:latest-postgresql and latest-backend, plus an
Alpine net-snmp snmpd. This file does not start them; scripts in the PR notes do.
"""

from __future__ import annotations

import os
import time

import pytest

from ie_config.app import create_app
from ie_config.settings import Settings


def _netdisco_up() -> bool:
    url = os.environ.get(
        "IE_NETDISCO_URL",
        "postgresql://netdisco:netdiscotest@127.0.0.1:54329/netdisco",
    )
    try:
        import psycopg
        with psycopg.connect(url, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM admin LIMIT 1")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _netdisco_up(), reason="Netdisco docker database is not running")


def test_api_discovers_snmp_device_and_reports_an_unreachable_address(tmp_path, monkeypatch):
    url = os.environ.get(
        "IE_NETDISCO_URL",
        "postgresql://netdisco:netdiscotest@127.0.0.1:54329/netdisco",
    )
    device_ip = os.environ.get("IE_SNMP_DEVICE", "10.99.0.10")
    out = os.environ.get("IE_NETDISCO_OUT", "/tmp/ie-nd-local")
    os.makedirs(out, exist_ok=True)
    cfg = tmp_path / "config" / "netdisco"
    cfg.mkdir(parents=True)
    (cfg / "deployment.yml").write_text(
        "device_auth:\n  - tag: default\n    community: ${SNMP_V2_COMMUNITY}\n",
        encoding="utf-8",
    )
    (tmp_path / "config" / "discovery").mkdir(parents=True)
    (tmp_path / "config" / "discovery" / "sync.yml").write_text(
        "prefix_selector: tag\ntag: ie-scan\ninterval_hours: 6\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SNMP_V2_COMMUNITY", "public")
    monkeypatch.setenv("IE_CONFIG_SCHEDULER", "0")
    settings = Settings(
        config_root=str(tmp_path),
        apps_file=os.path.join(os.path.dirname(os.path.dirname(__file__)), "apps.yml"),
        database_url="sqlite:///" + str(tmp_path / "ie.db"),
        history_dir=str(tmp_path / "history"),
        cookie_secure=False,
        cookie_name="ie_session",
        setup_token_file=str(tmp_path / "setup"),
        client_slug="dockertest",
        public_host="localhost",
        docker_proxy_url="http://127.0.0.1:9",
        scheduler=False,
        netbox_url="http://127.0.0.1:9",
        netbox_token_file=str(tmp_path / "no-token"),
        netdisco_database_url=url,
        netdisco_out_dir=out,
        mib_dir=str(tmp_path / "mibs"),
        candidate_dir=str(tmp_path / "cand"),
        generator_bin="missing",
    )
    (tmp_path / "setup").write_text("setup-token-value", encoding="utf-8")
    app = create_app(settings)
    # The test container is not the compose name. Restart it directly when device_auth changes.
    # The backend also watches deployment.yml; restart is the path the docker proxy allows.
    def _restart() -> bool:
        import subprocess
        proc = subprocess.run(
            ["sudo", "docker", "restart", "ie-nd-backend"],
            capture_output=True, text=True, timeout=90,
        )
        return proc.returncode == 0
    app.state.discovery.restart_backend = _restart
    app.state.discovery._snmp_sync = lambda: None

    from fastapi.testclient import TestClient
    client = TestClient(app)
    boot = client.post(
        "/internal/bootstrap-admin",
        headers={"Authorization": "Bearer setup-token-value"},
        json={"email": "admin@example.com", "password": "Adminpass1234"},
    )
    assert boot.status_code == 200, boot.text
    login = client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "Adminpass1234"})
    assert login.status_code == 200, login.text
    csrf = login.json()["csrfToken"]
    headers = {"X-CSRF-Token": csrf}

    missed = client.post(
        "/api/v1/discovery/device",
        headers=headers,
        json={"ip": "192.0.2.50", "neighbours": False},
    )
    assert missed.status_code == 200, missed.text
    assert missed.json()["status"] == "error"
    assert "public" not in missed.text
    assert "SNMP" in missed.json()["message"] or "snmp" in missed.json()["message"].lower() or "timed out" in missed.json()["message"]

    started = client.post(
        "/api/v1/discovery/device",
        headers=headers,
        json={"ip": device_ip, "neighbours": False},
    )
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["steps"][0]["status"] == "done"
    assert body["steps"][0]["message"].startswith("SNMP reachable via profile")
    assert "public" not in started.text

    deadline = time.time() + 180
    last = body
    while time.time() < deadline and last["status"] not in ("done", "error"):
        time.sleep(3)
        polled = client.get("/api/v1/discovery/device/" + body["id"])
        assert polled.status_code == 200, polled.text
        last = polled.json()
    assert last["status"] == "done", last
    names = [step["name"] for step in last["steps"]]
    assert names[:4] == ["snmp", "discover", "macsuck", "arpnip"]
    assert all(step["status"] == "done" for step in last["steps"][:4])

    import psycopg
    with psycopg.connect(url, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT host(ip)::text FROM device WHERE host(ip)::text = %s", (device_ip,))
            assert cur.fetchone() is not None

    listed = client.get("/api/v1/discovery/unapproved")
    assert listed.status_code == 200
    assert any(row.get("ip") == device_ip for row in listed.json()), listed.json()
