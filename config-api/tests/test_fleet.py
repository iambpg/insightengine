"""Fleet API tests. NetBox, Prometheus and Alertmanager are mocked; nothing listens."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from ie_config.app import create_app
from ie_config.fleet import FleetService, classify_health, form_factor_for, mask_serial
from ie_config.settings import Settings

NOW = datetime(2026, 10, 27, 14, 30, tzinfo=timezone.utc).timestamp()
TOKEN = "super-secret-token"

ROW_KEYS = {
    "id", "hostname", "role", "site", "siteId", "mgmtIp", "modelFamily", "health",
    "portsUp", "portsTotal", "portsWarn", "portsFault", "uptime", "lastPoll", "formFactor",
}
DETAIL_KEYS = {
    "id", "hostname", "role", "site", "siteId", "mgmtIp", "modelFamily", "health",
    "uptime", "lastPoll", "firmware", "serialMasked", "faceplate", "issues", "checks",
    "hardware", "checkRunAt",
}
SITE_KEYS = {"id", "name", "region", "city", "deviceCount", "health", "alerts", "lastDiscovery"}
ALERT_KEYS = {
    "id", "severity", "title", "detail", "site", "siteId", "deviceHostname", "formFactor",
    "category", "raisedAt", "ageMinutes", "status",
}
SERIES_KEYS = {"t", "label", "inBps", "outBps", "errors", "util"}


def _sample(host, ip, value, **extra):
    metric = {"hostname": host, "instance": ip}
    metric.update(extra)
    return {"metric": metric, "value": [NOW, str(value)]}


def _fleet_vector(query: str):
    if "probe_success" in query:
        return [
            _sample("core-1", "10.1.0.1", 1),
            _sample("edge-2", "10.1.0.2", 1),
            _sample("wan-3", "10.2.0.3", 0),
        ]
    # last_poll is `timestamp(...) or timestamp(up{...})` and must not match the up{} branch.
    if "timestamp(" in query:
        return [_sample("core-1", "10.1.0.1", NOW - 14), _sample("edge-2", "10.1.0.2", NOW - 30)]
    if query.startswith("max by") and "up{" in query:
        return [
            _sample("core-1", "10.1.0.1", 1),
            _sample("edge-2", "10.1.0.2", 1),
            _sample("wan-3", "10.2.0.3", 0),
        ]
    if "sysUpTime" in query:
        return [_sample("core-1", "10.1.0.1", 864000000), _sample("edge-2", "10.1.0.2", 360000)]
    if 'ifOperStatus="up"' in query or "ifOperStatus == 1" in query:
        return [_sample("core-1", "10.1.0.1", 3), _sample("edge-2", "10.1.0.2", 20)]
    if "ifAdminStatus" in query or "ifOperStatus == 2" in query:
        return []
    if "ifInErrors" in query:
        return [_sample("core-1", "10.1.0.1", 1)]
    if "ifOperStatus" in query:
        return [_sample("core-1", "10.1.0.1", 4), _sample("edge-2", "10.1.0.2", 24)]
    return []


def _detail_instant(query: str):
    up = {"metric": {"__name__": "ifOperStatus_info", "hostname": "core-1", "ifName": "Gi1/0/1", "ifIndex": "1", "ifOperStatus": "up"}, "value": [NOW, "1"]}
    down = {"metric": {"__name__": "ifOperStatus_info", "hostname": "core-1", "ifName": "Gi1/0/2", "ifIndex": "2", "ifOperStatus": "down"}, "value": [NOW, "1"]}
    if "ifOperStatus" in query:
        return [up, down]
    if "ifAdminStatus" in query:
        return [
            {"metric": {"__name__": "ifAdminStatus_info", "ifName": "Gi1/0/1", "ifIndex": "1", "ifAdminStatus": "up"}, "value": [NOW, "1"]},
            {"metric": {"__name__": "ifAdminStatus_info", "ifName": "Gi1/0/2", "ifIndex": "2", "ifAdminStatus": "up"}, "value": [NOW, "1"]},
        ]
    if "ifHighSpeed" in query:
        return [
            {"metric": {"ifName": "Gi1/0/1", "ifIndex": "1"}, "value": [NOW, "1000"]},
            {"metric": {"ifName": "Gi1/0/2", "ifIndex": "2"}, "value": [NOW, "10000"]},
        ]
    if "ifHCInOctets" in query:
        return [{"metric": {"ifName": "Gi1/0/1", "ifIndex": "1"}, "value": [NOW, "12500000"]}]
    if "ifHCOutOctets" in query:
        return [{"metric": {"ifName": "Gi1/0/1", "ifIndex": "1"}, "value": [NOW, "6250000"]}]
    if "ifInErrors" in query:
        return [{"metric": {"ifName": "Gi1/0/2", "ifIndex": "2"}, "value": [NOW, "2"]}]
    if "cpmCPU" in query or "fgSysCpu" in query:
        return [{"metric": {"hostname": "core-1"}, "value": [NOW, "23"]}]
    if "ciscoMemory" in query or "fgSysMem" in query:
        return [{"metric": {"hostname": "core-1"}, "value": [NOW, "40"]}]
    if "Temperature" in query:
        return [{"metric": {"hostname": "core-1"}, "value": [NOW, "47"]}]
    if "FanState" in query:
        return [{"metric": {"__name__": "ciscoEnvMonFanState_info", "ciscoEnvMonFanState": "normal"}, "value": [NOW, "1"]}]
    if "SupplyState" in query:
        return [
            {"metric": {"__name__": "ciscoEnvMonSupplyState_info", "ciscoEnvMonSupplyState": "normal", "ciscoEnvMonSupplyStatusIndex": "1"}, "value": [NOW, "1"]},
            {"metric": {"__name__": "ciscoEnvMonSupplyState_info", "ciscoEnvMonSupplyState": "critical", "ciscoEnvMonSupplyStatusIndex": "2"}, "value": [NOW, "1"]},
        ]
    if "probe_duration" in query:
        return [{"metric": {"hostname": "core-1"}, "value": [NOW, "0.0032"]}]
    return []


def _matrix(query: str):
    start = NOW - 60
    def series(a, b):
        return [{"metric": {"hostname": "core-1"}, "values": [[start, str(a)], [NOW, str(b)]]}]
    if "ifHCInOctets" in query:
        return series(10.5, 12)
    if "ifHCOutOctets" in query:
        return series(4, 5)
    if "ifInErrors" in query:
        return series(1, 2)
    if "cpmCPU" in query or "fgSysCpu" in query:
        return series(20, 23)
    if "Memory" in query or "fgSysMem" in query:
        return series(40, 41)
    if "Temperature" in query:
        return series(46, 47)
    return []


class Upstream:
    def __init__(self):
        self.devices = _devices()
        self.sites = _sites()
        self.alerts = _alerts()
        self.silences = _silences()
        self.netbox = "ok"
        self.prometheus = "ok"
        self.alertmanager = "ok"
        self.calls = []
        self.posted = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        path = request.url.path
        auth = request.headers.get("authorization", "")
        self.calls.append((host, path, auth, request.method))
        if host.startswith("netbox"):
            return self._netbox(request, path)
        if host.startswith("prometheus"):
            return self._prom(request, path)
        if host.startswith("alertmanager"):
            return self._am(request, path)
        return httpx.Response(404, json={"error": "unknown"})

    def _netbox(self, request, path):
        if self.netbox == "down":
            raise httpx.ConnectError("netbox down")
        if self.netbox == "http":
            return httpx.Response(503, json={"detail": "unavailable"})
        if path.startswith("/api/dcim/devices"):
            return httpx.Response(200, json={"count": len(self.devices), "next": None, "results": self.devices})
        if path.startswith("/api/dcim/sites"):
            return httpx.Response(200, json={"count": len(self.sites), "next": None, "results": self.sites})
        return httpx.Response(404, json={"detail": "missing"})

    def _prom(self, request, path):
        if self.prometheus == "down":
            raise httpx.ConnectError("prometheus down")
        if path.endswith("/-/healthy"):
            return httpx.Response(200, text="ok")
        query = request.url.params.get("query", "")
        if path.endswith("/query_range"):
            result = _matrix(query)
            return httpx.Response(200, json={"status": "success", "data": {"resultType": "matrix", "result": result}})
        if path.endswith("/query"):
            fleet = query.startswith("max by") or query.startswith("count by")
            result = _fleet_vector(query) if fleet else _detail_instant(query)
            return httpx.Response(200, json={"status": "success", "data": {"resultType": "vector", "result": result}})
        return httpx.Response(404, text="no")

    def _am(self, request, path):
        if self.alertmanager == "down":
            raise httpx.ConnectError("alertmanager down")
        if path.endswith("/-/healthy"):
            return httpx.Response(200, text="ok")
        if path.endswith("/silences") and request.method == "POST":
            body = json.loads(request.content.decode() or "{}")
            self.posted.append(body)
            return httpx.Response(200, json={"silenceID": "sil-new"})
        if path.endswith("/silences"):
            return httpx.Response(200, json=self.silences)
        if path.endswith("/alerts"):
            return httpx.Response(200, json=self.alerts)
        return httpx.Response(404, text="no")


def _devices():
    def one(id_, name, slug, role, site_id, site, model, ip, serial="", platform=""):
        return {
            "id": id_, "name": name, "serial": serial, "last_updated": "2026-10-27T14:00:00Z",
            "role": {"name": role, "slug": slug},
            "site": {"id": site_id, "name": site, "slug": site.lower()},
            "device_type": {"model": model, "manufacturer": {"name": "Cisco"}},
            "primary_ip4": {"address": ip + "/32"},
            "platform": {"name": platform} if platform else None,
        }
    return [
        one(10, "core-1", "core-switch", "Core Switch", 1, "Rotterdam", "C9500", "10.1.0.1", "ABCDEF123456", "IOS-XE 17.9"),
        one(11, "edge-2", "access-switch", "Access Switch", 1, "Rotterdam", "C9300-24P", "10.1.0.2"),
        one(12, "wan-3", "sdwan", "SD-WAN", 2, "Amsterdam", "FG-60F", "10.2.0.3"),
    ]


def _sites():
    return [
        {
            "id": 1, "name": "Rotterdam", "slug": "rotterdam", "last_updated": "2026-10-27T12:00:00Z",
            "region": {"name": "Benelux-West", "slug": "benelux-west"},
            "physical_address": "Havenstraat 1\nRotterdam",
        },
        {
            "id": 2, "name": "Amsterdam", "slug": "amsterdam", "last_updated": "2026-10-27T10:00:00Z",
            "region": {"name": "Benelux-North", "slug": "benelux-north"},
            "physical_address": "Dam 1, Amsterdam",
        },
    ]


def _alerts():
    return [
        {
            "fingerprint": "fp1",
            "startsAt": "2026-10-27T14:20:00Z",
            "status": {"state": "active", "silencedBy": [], "inhibitedBy": []},
            "labels": {"alertname": "DeviceUnreachable", "severity": "critical", "hostname": "core-1", "site": "Rotterdam"},
            "annotations": {"summary": "Core switch offline", "description": "No ICMP for 6 minutes"},
        },
        {
            "fingerprint": "fp2",
            "startsAt": "2026-10-27T13:30:00Z",
            "status": {"state": "suppressed", "silencedBy": ["sil1"], "inhibitedBy": []},
            "labels": {"alertname": "HighCPU", "severity": "warning", "hostname": "edge-2", "site": "Rotterdam"},
            "annotations": {"summary": "CPU high", "description": "CPU above 80%"},
        },
    ]


def _silences():
    return [{
        "id": "sil1",
        "status": {"state": "active"},
        "createdBy": "admin@example.com",
        "startsAt": "2026-10-27T14:00:00Z",
        "matchers": [],
    }]


def _settings(tmp_path: Path, **overrides) -> Settings:
    secret = tmp_path / "netbox.token"
    secret.write_text(TOKEN + "\n", encoding="utf-8")
    values = dict(
        config_root=str(tmp_path),
        apps_file=str(tmp_path / "apps.yml"),
        database_url="sqlite:///" + str(tmp_path / "ie.db"),
        history_dir=str(tmp_path / "history"),
        cookie_secure=False,
        cookie_name="ie_session",
        setup_token_file=str(tmp_path / "setup-token"),
        client_slug="test",
        public_host="localhost",
        docker_proxy_url="http://127.0.0.1:9",
        scheduler=False,
        netbox_url="http://netbox.test",
        netbox_token_file=str(secret),
        netdisco_database_url="",
        netdisco_out_dir=str(tmp_path / "nd"),
        mib_dir=str(tmp_path / "mibs"),
        candidate_dir=str(tmp_path / "cand"),
        generator_bin="/usr/local/bin/generator-missing",
        prometheus_url="http://prometheus.test",
        alertmanager_url="http://alertmanager.test",
        ca_file=str(tmp_path / "missing-ca.crt"),
        fleet_cache_seconds=30,
        alert_webhook_token_file="",
    )
    values.update(overrides)
    (tmp_path / "setup-token").write_text("setup-token-value", encoding="utf-8")
    (tmp_path / "apps.yml").write_text("version: 1\napps: []\n", encoding="utf-8")
    return Settings(**values)


@pytest.fixture()
def stack(tmp_path, monkeypatch):
    monkeypatch.setenv("IE_CONFIG_SCHEDULER", "0")
    monkeypatch.setenv("COOKIE_SECURE", "0")
    upstream = Upstream()
    http = httpx.Client(transport=httpx.MockTransport(upstream.handle))
    settings = _settings(tmp_path)
    fleet = FleetService(settings, client=http, now=lambda: NOW)
    app = create_app(settings, fleet=fleet)
    client = TestClient(app)
    return {"client": client, "up": upstream, "fleet": fleet, "settings": settings, "root": tmp_path}


def _bootstrap(client, email="admin@example.com", password="Adminpass1234"):
    response = client.post(
        "/internal/bootstrap-admin",
        headers={"Authorization": "Bearer setup-token-value"},
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text


def _login(client, email="admin@example.com", password="Adminpass1234"):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["csrfToken"]


def _auth(stack):
    _bootstrap(stack["client"])
    return _login(stack["client"])


def test_classify_and_form_helpers():
    assert classify_health(None, None, None, 0, 0, 0) == "unreachable"
    assert classify_health(0, 1, 10, 0, 0, 4) == "unreachable"
    assert classify_health(1, 1, 10, 2, 0, 4) == "critical"
    assert classify_health(1, 1, 10, 0, 1, 4) == "warning"
    assert classify_health(1, 0, 10, 0, 0, 4) == "warning"
    assert classify_health(1, 1, 10, 0, 0, 4) == "healthy"
    assert classify_health(1, 1, 4000, 0, 0, 4) == "unreachable"
    assert form_factor_for("access-switch", "Access Switch", "C9300-24P") == ("Access switch", "access-switch-24")
    assert form_factor_for("access-switch", "Access Switch", "C9300-48P") == ("Access switch", "access-switch-48")
    assert form_factor_for("core-switch", "Core", "C9500")[1] == "modular-chassis"
    assert form_factor_for("sdwan", "SD-WAN", "FG-60F") == ("Firewall", "firewall")
    assert form_factor_for("distribution-switch", "Distribution", "stack")[1] == "switch-stack"
    assert mask_serial("ABCDEF123456") == "ABC••••••456"
    assert mask_serial("") == "—"


def test_requires_session(stack):
    client = stack["client"]
    for path in (
        "/api/v1/summary",
        "/api/v1/devices?page=1&page_size=25",
        "/api/v1/devices/switch-stack",
        "/api/v1/devices/10/metrics/throughput?range=1h",
        "/api/v1/devices/10/metrics/resources?range=1h",
        "/api/v1/devices/10/ports/top?metric=util",
        "/api/v1/devices/10/ports/1/metrics?range=1h",
        "/api/v1/sites",
        "/api/v1/sites/1/devices",
        "/api/v1/alerts",
        "/api/v1/health",
    ):
        response = client.get(path)
        assert response.status_code == 401, path
        assert response.json()["error"]["code"] == "unauthorized"
    denied = client.post("/api/v1/alerts/acknowledge", json={"ids": ["fp1"]})
    assert denied.status_code == 401


def test_empty_install_is_not_an_error(stack):
    _auth(stack)
    stack["up"].devices = []
    stack["up"].sites = []
    stack["up"].alerts = []
    stack["up"].silences = []
    client = stack["client"]
    summary = client.get("/api/v1/summary")
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["total"] == 0
    assert body["healthy"] == body["warning"] == body["critical"] == body["unreachable"] == 0
    assert body["alerts"] == 0
    assert body["isExampleData"] is False
    devices = client.get("/api/v1/devices?page=1&page_size=25&q=&health=all&role=all&sort=hostname:asc")
    assert devices.status_code == 200
    assert devices.json()["rows"] == []
    assert devices.json()["total"] == 0
    sites = client.get("/api/v1/sites?page=1&page_size=10&q=&health=all&region=all")
    assert sites.status_code == 200
    assert sites.json()["rows"] == []
    assert sites.json()["total"] == 0
    assert client.get("/api/v1/sites/1/devices").json() == []
    alerts = client.get("/api/v1/alerts")
    assert alerts.status_code == 200
    assert alerts.json() == []
    detail = client.get("/api/v1/devices/switch-stack")
    assert detail.status_code == 200, detail.text
    empty = detail.json()
    assert DETAIL_KEYS <= set(empty)
    assert empty["hostname"] == "—"
    assert empty["faceplate"]["form_factor"] == "switch-stack"
    assert empty["issues"] == []
    assert client.get("/api/v1/devices/switch-stack/metrics/throughput?range=1h").json() == []
    assert client.get("/api/v1/devices/switch-stack/ports/top?metric=util").json() == []
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["upstreams"]["netbox"]["ok"] is True
    assert TOKEN not in summary.text


def test_populated_shapes_filters_and_paging(stack):
    _auth(stack)
    client = stack["client"]
    listed = client.get("/api/v1/devices?page=1&page_size=2&q=&health=all&role=all&sort=hostname:asc")
    assert listed.status_code == 200, listed.text
    page = listed.json()
    assert page["total"] == 3
    assert page["isExampleData"] is False
    assert [row["hostname"] for row in page["rows"]] == ["core-1", "edge-2"]
    assert ROW_KEYS <= set(page["rows"][0])
    assert "Access switch" in page["roles"]
    assert "Firewall" in page["roles"]
    second = client.get("/api/v1/devices?page=2&page_size=2&sort=hostname:asc")
    assert [row["hostname"] for row in second.json()["rows"]] == ["wan-3"]
    # Inventory is cached: one NetBox device page for both lists, not one call per device.
    device_calls = [c for c in stack["up"].calls if c[0].startswith("netbox") and c[1].startswith("/api/dcim/devices")]
    assert len(device_calls) == 1
    assert all(c[2].startswith("Token ") for c in device_calls)
    assert all(not c[2] for c in stack["up"].calls if c[0].startswith("prometheus"))

    found = client.get("/api/v1/devices?q=10.2&health=all&role=all&sort=hostname:asc").json()
    assert [row["hostname"] for row in found["rows"]] == ["wan-3"]
    warned = client.get("/api/v1/devices?health=warning&role=all").json()
    assert [row["hostname"] for row in warned["rows"]] == ["core-1"]
    assert warned["rows"][0]["portsWarn"] == 1
    assert warned["rows"][0]["portsUp"] == 3
    switched = client.get("/api/v1/devices?role=Access%20switch&health=all").json()
    assert [row["hostname"] for row in switched["rows"]] == ["edge-2"]
    assert switched["rows"][0]["formFactor"] == "access-switch-24"
    by_slug = client.get("/api/v1/devices?role=access-switch").json()
    assert [row["hostname"] for row in by_slug["rows"]] == ["edge-2"]
    down = client.get("/api/v1/devices?health=unreachable").json()["rows"]
    assert [row["hostname"] for row in down] == ["wan-3"]
    assert down[0]["uptime"] == "—"
    assert down[0]["portsUp"] == 0
    order = client.get("/api/v1/devices?sort=hostname:desc&page_size=10").json()["rows"]
    assert [row["hostname"] for row in order] == ["wan-3", "edge-2", "core-1"]
    none = client.get("/api/v1/devices?q=does-not-exist").json()
    assert none["rows"] == [] and none["total"] == 0

    summary = client.get("/api/v1/summary").json()
    assert summary["total"] == 3
    assert summary["healthy"] == 1
    assert summary["warning"] == 1
    assert summary["critical"] == 0
    assert summary["unreachable"] == 1
    assert summary["alerts"] == 1
    assert summary["isExampleData"] is False

    sites = client.get("/api/v1/sites?page=1&page_size=10&q=&health=all&region=all")
    assert sites.status_code == 200, sites.text
    site_body = sites.json()
    assert site_body["total"] == 2
    assert SITE_KEYS <= set(site_body["rows"][0])
    assert "Benelux-West" in site_body["regions"]
    west = client.get("/api/v1/sites?region=Benelux-West").json()["rows"]
    assert [row["name"] for row in west] == ["Rotterdam"]
    assert west[0]["city"] == "Rotterdam"
    assert west[0]["deviceCount"] == 2
    assert west[0]["alerts"] == 1
    searched = client.get("/api/v1/sites?q=amster").json()["rows"]
    assert [row["name"] for row in searched] == ["Amsterdam"]
    members = client.get("/api/v1/sites/1/devices")
    assert members.status_code == 200
    assert [row["hostname"] for row in members.json()] == ["core-1", "edge-2"]
    assert ROW_KEYS <= set(members.json()[0])
    assert [row["hostname"] for row in client.get("/api/v1/sites/rotterdam/devices").json()] == ["core-1", "edge-2"]
    assert client.get("/api/v1/sites/site-2/devices").json()[0]["hostname"] == "wan-3"
    assert client.get("/api/v1/sites/missing/devices").json() == []

    detail = client.get("/api/v1/devices/10")
    assert detail.status_code == 200, detail.text
    device = detail.json()
    assert DETAIL_KEYS <= set(device)
    assert device["hostname"] == "core-1"
    assert device["serialMasked"] == "ABC••••••456"
    assert device["firmware"] == "IOS-XE 17.9"
    assert device["faceplate"]["form_factor"] == "modular-chassis"
    ports = device["faceplate"]["modules"][0]["ports"]
    assert [port["name"] for port in ports] == ["Gi1/0/1", "Gi1/0/2"]
    assert {port["id"] for port in ports} == {"1", "2"}
    assert ports[0]["state"] == "up"
    assert ports[1]["state"] == "fault"
    assert ports[0]["type"] == "RJ45"
    assert any(item["kind"] == "power" and item["status"] == "fail" for item in device["hardware"])
    assert any(issue["severity"] == "critical" for issue in device["issues"])
    by_form = client.get("/api/v1/devices/access-switch-24").json()
    assert by_form["hostname"] == "edge-2"
    assert by_form["faceplate"]["form_factor"] == "access-switch-24"
    missing = client.get("/api/v1/devices/does-not-exist")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"

    series = client.get("/api/v1/devices/10/metrics/throughput?range=1h")
    assert series.status_code == 200, series.text
    point = series.json()[0]
    assert SERIES_KEYS <= set(point)
    assert isinstance(point["t"], int)
    assert point["inBps"] == 10.5
    resources = client.get("/api/v1/devices/10/metrics/resources?range=24h").json()
    assert {"t", "label", "cpu", "mem", "temp"} <= set(resources[0])
    assert resources[-1]["cpu"] == 23
    top = client.get("/api/v1/devices/10/ports/top?metric=util").json()
    assert top[0]["name"] == "Gi1/0/1"
    assert "util" in top[0]
    port = client.get("/api/v1/devices/10/ports/1/metrics?range=1h").json()
    assert SERIES_KEYS <= set(port[0])
    legacy = client.get("/api/v1/devices/ports/Gi1~0~1/metrics?range=1h")
    assert legacy.status_code == 200
    assert legacy.json()[0]["inBps"] == 10.5
    bad_metric = client.get("/api/v1/devices/10/ports/top?metric=errors")
    assert bad_metric.status_code == 400
    bad_page = client.get("/api/v1/devices?page=abc")
    assert bad_page.status_code == 400

    alerts = client.get("/api/v1/alerts")
    assert alerts.status_code == 200, alerts.text
    items = alerts.json()
    assert ALERT_KEYS <= set(items[0])
    by_id = {item["id"]: item for item in items}
    assert by_id["fp1"]["severity"] == "critical"
    assert by_id["fp1"]["status"] == "open"
    assert by_id["fp1"]["deviceHostname"] == "core-1"
    assert by_id["fp1"]["formFactor"] == "modular-chassis"
    assert by_id["fp1"]["ageMinutes"] == 10
    assert by_id["fp2"]["status"] == "acknowledged"
    assert by_id["fp2"]["acknowledgedBy"] == "admin@example.com"
    critical = client.get("/api/v1/alerts?severity=critical&status=open&site=Rotterdam").json()
    assert [item["id"] for item in critical] == ["fp1"]


def test_acknowledge_creates_silence_as_the_user(stack):
    csrf = _auth(stack)
    client = stack["client"]
    missing = client.post("/api/v1/alerts/acknowledge", json={"ids": ["fp1"]})
    assert missing.status_code == 403
    ok = client.post(
        "/api/v1/alerts/acknowledge",
        json={"ids": ["fp1"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json() == {"ids": ["fp1"], "ok": True}
    posted = stack["up"].posted[0]
    assert posted["createdBy"] == "admin@example.com"
    assert posted["comment"] == "Acknowledged in InsightEngine"
    names = {matcher["name"]: matcher for matcher in posted["matchers"]}
    assert names["alertname"]["value"] == "DeviceUnreachable"
    assert names["alertname"]["isRegex"] is False
    assert names["hostname"]["value"] == "core-1"
    assert TOKEN not in json.dumps(posted)
    unknown = client.post(
        "/api/v1/alerts/acknowledge",
        json={"ids": ["missing"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert unknown.status_code == 404
    empty = client.post("/api/v1/alerts/acknowledge", json={"ids": []}, headers={"X-CSRF-Token": csrf})
    assert empty.status_code == 400


def test_read_only_cannot_acknowledge(stack):
    csrf = _auth(stack)
    client = stack["client"]
    created = client.post(
        "/api/v1/auth/users",
        json={"email": "reader@example.com", "password": "Readerpass1234", "role": "Read-only"},
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 200, created.text
    client.post("/api/v1/auth/logout")
    reader = _login(client, "reader@example.com", "Readerpass1234")
    denied = client.post(
        "/api/v1/alerts/acknowledge",
        json={"ids": ["fp1"]},
        headers={"X-CSRF-Token": reader},
    )
    assert denied.status_code == 403
    assert client.get("/api/v1/devices").status_code == 200


def test_webhook_and_upstream_failures(stack, monkeypatch):
    client = stack["client"]
    accepted = client.post("/api/v1/alerts/webhook", json={"alerts": [{"labels": {"alertname": "DeviceUnreachable"}}]})
    assert accepted.status_code == 200
    assert accepted.json() == {"ok": True, "received": 1}
    assert client.post("/api/v1/alerts/webhook", json=[]).status_code == 400
    monkeypatch.setenv("ALERT_WEBHOOK_TOKEN", "hook-secret")
    denied = client.post("/api/v1/alerts/webhook", json={"alerts": []})
    assert denied.status_code == 401
    allowed = client.post(
        "/api/v1/alerts/webhook",
        json={"alerts": []},
        headers={"Authorization": "Bearer hook-secret"},
    )
    assert allowed.status_code == 200
    assert TOKEN not in accepted.text

    _auth(stack)
    stack["up"].prometheus = "down"
    stack["fleet"].cache.drop("prom-fleet")
    listed = client.get("/api/v1/devices")
    assert listed.status_code == 200, listed.text
    assert "prometheus" in listed.json()["degraded"]
    assert all(row["health"] == "unreachable" for row in listed.json()["rows"])
    health = client.get("/api/v1/health").json()
    assert health["status"] == "degraded"
    assert health["ok"] is False
    assert health["upstreams"]["prometheus"]["status"] == "down"
    assert health["upstreams"]["netbox"]["ok"] is True

    stack["up"].prometheus = "ok"
    stack["up"].alertmanager = "down"
    stack["fleet"].cache.drop("am-alerts")
    alerts = client.get("/api/v1/alerts")
    assert alerts.status_code == 502
    assert alerts.json()["error"]["code"] == "upstream_unavailable"
    assert alerts.json()["error"]["details"]["upstream"] == "alertmanager"
    metrics = client.get("/api/v1/devices/10/metrics/throughput?range=1h")
    # Prometheus is healthy again; empty-or-populated series is still a list.
    stack["up"].prometheus = "ok"
    stack["fleet"].cache.drop("prom-fleet")
    assert client.get("/api/v1/devices/10/metrics/throughput?range=1h").status_code == 200

    stack["up"].netbox = "down"
    stack["fleet"].cache.drop("nb-devices")
    stack["fleet"].cache.drop("nb-sites")
    stack["fleet"].cache.drop("prom-fleet")
    failed = client.get("/api/v1/summary")
    assert failed.status_code == 502
    assert failed.json()["error"]["code"] == "upstream_unavailable"
    assert "NetBox" in failed.json()["error"]["message"]
    assert TOKEN not in failed.text
    assert metrics.status_code in (200, 502)


def test_missing_token_is_a_clear_error(stack):
    _auth(stack)
    path = Path(stack["settings"].netbox_token_file)
    path.write_text("unset-placeholder\n", encoding="utf-8")
    stack["fleet"].cache.drop("nb-devices")
    stack["fleet"].cache.drop("nb-sites")
    failed = stack["client"].get("/api/v1/devices")
    assert failed.status_code == 502
    assert "token" in failed.json()["error"]["message"].lower()
    assert TOKEN not in failed.text
    health = stack["client"].get("/api/v1/health").json()
    assert health["upstreams"]["netbox"]["status"] == "unconfigured"
