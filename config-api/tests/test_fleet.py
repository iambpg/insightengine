"""Fleet API tests. NetBox, Prometheus and Alertmanager are mocked; nothing listens."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from ie_config.app import create_app
from ie_config.fleet import FleetService, classify_device, classify_health, form_factor_for, is_form_key, mask_serial
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
        self.interfaces = {}

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
        if path.startswith("/api/dcim/interfaces"):
            device_id = request.url.params.get("device_id", "")
            rows = list(self.interfaces.get(str(device_id), []))
            try:
                offset = int(request.url.params.get("offset") or 0)
            except ValueError:
                offset = 0
            page = rows[offset:offset + 200]
            nxt = None
            if offset + 200 < len(rows):
                nxt = "http://netbox.test/api/dcim/interfaces/?device_id=%s&limit=200&offset=%s" % (device_id, offset + 200)
            return httpx.Response(200, json={"count": len(rows), "next": nxt, "results": page})
        if path.startswith("/api/ipam/ip-addresses"):
            return httpx.Response(200, json={"count": 0, "next": None, "results": []})
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
    assert is_form_key("firewall") is True
    assert is_form_key("access-switch-48") is True
    assert is_form_key("fg-edge") is False
    assert is_form_key("pa-820") is False
    assert mask_serial("ABCDEF123456") == "ABC••••••456"
    assert mask_serial("") == "—"

    fortigate = classify_device(
        {"role_name": "Security", "role_slug": "security", "manufacturer": "Fortinet", "model": "FortiGate 60F", "hostname": "apc-ups"},
        None,
    )
    assert fortigate["form"] == "firewall"
    assert fortigate["kind"] != "ap"
    palo = classify_device(
        {"role_name": "Security", "role_slug": "security", "manufacturer": "Palo Alto", "model": "PA-820"},
        None,
    )
    assert palo["form"] == "firewall"
    catalyst = classify_device(
        {"role_slug": "access-switch", "role_name": "Access Switch", "manufacturer": "Cisco", "model": "Catalyst 9300-48P"},
        None,
    )
    assert catalyst["form"] == "access-switch-48"
    isr = classify_device(
        {"role_name": "Edge", "role_slug": "edge", "manufacturer": "Cisco", "model": "ISR4451"},
        None,
    )
    assert isr["form"] == "branch-router"
    air = classify_device(
        {"role_name": "Device", "role_slug": "device", "manufacturer": "Cisco", "model": "AIR-AP2802I-E-K9"},
        None,
    )
    assert air["form"] == "ceiling-ap"
    ups = classify_device(
        {"hostname": "apc-ups", "role_slug": "ups", "role_name": "UPS", "manufacturer": "APC", "model": "Smart-UPS 3000"},
        None,
    )
    assert ups["form"] == "generic"
    assert ups["form"] != "ceiling-ap"
    mislabelled = classify_device(
        {
            "role_slug": "access-point",
            "role_name": "Access Point",
            "manufacturer": "Cisco",
            "model": "C9300-48P",
            "hostname": "apc-ups",
            "interfaces": [{"name": "Gi1/0/1", "type": "1000base-t", "enabled": True}],
        },
        {
            "vendor": "cisco",
            "model": "C9300-48P",
            "description": "Cisco IOS Software, Catalyst L3 Switch",
            "ports": [{"name": "Gi1/0/%d" % n, "type": "ethernetCsmacd", "speed": "1000", "up": "up"} for n in range(1, 49)]
            + [{"name": "Te1/1/%d" % n, "type": "sfp", "speed": "10000", "up": "up"} for n in range(1, 5)],
        },
    )
    assert mislabelled["form"] == "access-switch-48"
    assert mislabelled["faceplate_source"] == "netdisco"
    assert mislabelled["comparison"]["differ"] is True
    assert mislabelled["comparison"]["faceplateSource"] == "netdisco"


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
    assert detail.status_code == 404, detail.text
    assert detail.json()["error"]["code"] == "not_found"
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
    assert warned["rows"] == []
    critical_rows = client.get("/api/v1/devices?health=critical&role=all").json()
    assert [row["hostname"] for row in critical_rows["rows"]] == ["core-1"]
    assert critical_rows["rows"][0]["portsWarn"] == 1
    assert critical_rows["rows"][0]["portsUp"] == 3
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
    assert summary["warning"] == 0
    assert summary["critical"] == 1
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
    assert device["health"] == "critical"
    causes = device["healthItems"]
    assert any(item["source"] == "alertmanager" and item["severity"] == "critical" for item in causes)
    assert any(item["title"] == "Power supply degraded" and item["severity"] == "critical" for item in causes)
    assert any(item["title"] == "Interface down" for item in causes)
    assert device["health"] == "critical"
    assert device["backup"]["available"] is False
    assert {row["name"] for row in device["sources"]} >= {"netbox", "prometheus", "alertmanager", "oxidized", "netdisco"}
    assert isinstance(device["interfaces"], list)
    assert isinstance(device["addresses"], list)
    assert device["status"] == "active"
    assert device["comparison"]["faceplateSource"] == "prometheus"
    assert device["comparison"]["differ"] is False
    assert isinstance(device["neighbors"], list)
    assert isinstance(device["history"], list)
    by_form = client.get("/api/v1/devices/access-switch-24")
    assert by_form.status_code == 404
    assert by_form.json()["error"]["message"] == "unknown device"
    by_name = client.get("/api/v1/devices/EDGE-2")
    assert by_name.status_code == 200, by_name.text
    assert by_name.json()["hostname"] == "edge-2"
    assert by_name.json()["faceplate"]["form_factor"] == "access-switch-24"
    by_ip = client.get("/api/v1/devices/10.1.0.2")
    assert by_ip.status_code == 200, by_ip.text
    assert by_ip.json()["id"] == "11"
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
    blocked = client.post(
        "/api/v1/access-points/approve",
        json={"role": "access-point", "site": "Rotterdam", "accessPoints": [{"name": "ap-1"}]},
        headers={"X-CSRF-Token": reader},
    )
    assert blocked.status_code == 403


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


def test_resolve_id_name_ip_status_netdisco_and_paging(stack, monkeypatch):
    _auth(stack)
    client = stack["client"]
    offline = {
        "id": 40,
        "name": "apc-ups",
        "serial": "UPS123456789",
        "status": {"value": "offline", "label": "Offline"},
        "role": {"name": "UPS", "slug": "ups"},
        "site": {"id": 1, "name": "Rotterdam", "slug": "rotterdam"},
        "device_type": {"model": "Smart-UPS 3000", "manufacturer": {"name": "APC"}},
        "primary_ip4": {"address": "10.9.0.40/32"},
        "platform": {"name": "UPS"},
    }
    stack["up"].devices.append(offline)
    stack["fleet"].cache.drop("nb-devices")
    listed = client.get("/api/v1/devices?page=1&page_size=50&health=all&role=all")
    assert listed.status_code == 200, listed.text
    ups = next(row for row in listed.json()["rows"] if row["hostname"] == "apc-ups")
    assert ups["status"] == "offline"
    assert ups["formFactor"] == "generic"
    assert ups["formFactor"] != "ceiling-ap"
    detail = client.get("/api/v1/devices/APC-UPS")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["id"] == "40"
    assert body["status"] == "offline"
    assert body["faceplate"]["form_factor"] == "generic"
    assert body["role"] == "UPS"
    by_ip = client.get("/api/v1/devices/10.9.0.40")
    assert by_ip.status_code == 200
    assert by_ip.json()["hostname"] == "apc-ups"
    form_key = client.get("/api/v1/devices/ceiling-ap")
    assert form_key.status_code == 404
    assert form_key.json()["error"]["message"] == "unknown device"
    assert client.get("/api/v1/devices/ceiling-ap/metrics/throughput?range=1h").json() == []

    interfaces = [
        {"id": index, "name": "Gi1/0/%d" % index, "type": {"value": "1000base-t", "label": "1000BASE-T"}, "enabled": True}
        for index in range(1, 202)
    ]
    stack["up"].interfaces["10"] = interfaces
    stack["fleet"].cache.drop("ports:core-1")
    paged = client.get("/api/v1/devices/10")
    assert paged.status_code == 200, paged.text
    paged_body = paged.json()
    assert len(paged_body["interfaces"]) == 201
    face_ports = paged_body["faceplate"]["modules"][0]["ports"]
    assert len(face_ports) == 201
    assert paged_body["comparison"]["faceplateSource"] == "netbox"
    assert paged_body["comparison"]["netbox"]["portCount"] == 201
    assert paged_body["faceplate"]["form_factor"] == "modular-chassis"

    def fake_find(_url, key, suffixes=None):
        if key not in ("10.9.9.9", "nd-orphan"):
            return None
        ports = [
            {"name": "Gi1/0/%d" % n, "type": "ethernetCsmacd", "speed": "1000", "up": "up", "admin": "up"}
            for n in range(1, 25)
        ]
        return {
            "available": True,
            "reason": "",
            "device": {
                "ip": "10.9.9.9",
                "dns": "nd-orphan",
                "name": "nd-orphan",
                "description": "Cisco IOS Software, Catalyst L3 Switch",
                "vendor": "Cisco",
                "model": "C9300-24P",
                "os": "ios",
                "os_ver": "17.9",
                "serial": "NDSERIAL1",
            },
            "ports": ports,
            "neighbors": [],
        }

    monkeypatch.setattr("ie_config.fleet.netdisco_find", fake_find)
    orphan = client.get("/api/v1/devices/10.9.9.9")
    assert orphan.status_code == 200, orphan.text
    orphan_body = orphan.json()
    assert orphan_body["netdiscoOnly"] is True
    assert orphan_body["status"] == "netdisco-only"
    assert orphan_body["hostname"] == "nd-orphan"
    assert orphan_body["faceplate"]["form_factor"] == "access-switch-24"
    assert orphan_body["comparison"]["faceplateSource"] == "netdisco"
    assert orphan_body["comparison"]["netdisco"]["vendor"] == "Cisco"
    assert orphan_body["comparison"]["netdisco"]["model"] == "C9300-24P"
    assert len(orphan_body["faceplate"]["ports"]) == 24
    by_nd_name = client.get("/api/v1/devices/nd-orphan")
    assert by_nd_name.status_code == 200
    assert by_nd_name.json()["mgmtIp"] == "10.9.9.9"
    assert client.get("/api/v1/devices/10.9.9.9/metrics/throughput?range=1h").json() == []
    access = stack["fleet"].device_access("10.9.9.9")
    assert access["hostname"] == "nd-orphan"
    assert access["manufacturer"] == "Cisco"
    from ie_config.errors import ApiError
    with pytest.raises(ApiError) as caught:
        stack["fleet"].device_access("firewall")
    assert caught.value.status == 404


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


def test_access_point_page_and_netbox_approve(stack, monkeypatch):
    csrf = _auth(stack)
    stack["fleet"].cache.put("ap-snapshot", {"degraded": False, "rows": [{
        "name": "ap-1",
        "serial": "FGLNEW",
        "wlc": "wlc-1",
        "model": "C9120AXI",
        "ip": "10.8.0.10",
        "ios": "17.12.1",
        "status": "down",
        "clients": 3,
        "mac": "aa:bb",
        "location": "floor-1",
        "siteTag": "Rotterdam",
        "site": "",
        "netboxSite": "",
        "radios": [{"slot": "0", "utilization": 0.81, "channel": 36, "clients": 3}],
        "ssids": [],
        "neighborSwitch": "core-1",
        "neighborPort": "Gi1/0/1",
        "uptimeSeconds": 120,
    }]})
    detail = stack["client"].get("/api/v1/devices/ap%3Aap-1")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["hostname"] == "ap-1"
    assert body["inNetbox"] is False
    assert body["role"] == "Access point"
    assert body["health"] == "critical"
    assert any(item["title"] == "Access point down" for item in body["healthItems"])
    assert any(item["source"] == "telegraf" and item["severity"] == "warning" for item in body["healthItems"])
    assert body["healthPanel"]["accessPoint"]["wlc"] == "wlc-1"
    assert body["healthPanel"]["accessPoint"]["serial"] == "FGLNEW"
    assert body["healthPanel"]["accessPoint"]["clients"] == 3
    assert body["neighbors"][0]["remoteName"] == "core-1"
    assert body["neighbors"][0]["protocol"] == "cdp"

    calls = []

    def fake(self, ap, **kwargs):
        calls.append((ap["name"], kwargs.get("role"), kwargs.get("site"), ap.get("serial")))
        return {"device_id": 42, "name": ap["name"]}

    monkeypatch.setattr("ie_config.fleet.NetBoxWriter.approve_access_point", fake)
    created = stack["client"].post(
        "/api/v1/access-points/approve",
        json={
            "role": "access-point",
            "site": "Rotterdam",
            "accessPoints": [
                {"name": "ap-1", "wlc": "wlc-1", "serial": "FGLNEW", "model": "C9120AXI", "ip": "10.8.0.10", "ios": "17.12.1"},
                {"name": "ap-old", "wlc": "wlc-1", "serial": "ABCDEF123456"},
            ],
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 200, created.text
    results = {row["name"]: row["status"] for row in created.json()["results"]}
    assert results == {"ap-1": "created", "ap-old": "skipped"}
    assert calls == [("ap-1", "access-point", "Rotterdam", "FGLNEW")]
    audit = stack["client"].get("/api/v1/settings/audit?app=netbox")
    assert audit.status_code == 200, audit.text
    actions = [row["action"] for row in audit.json()["entries"] if row["action"] == "ap-approve"]
    assert len(actions) == 2


def test_ap_online_from_info_without_oper_metric(stack):
    """Old ie_wlc_ap_info has no state label. A fresh sample is still online.

    The name is sometimes the wtp-mac key. The same hostname with two MACs
    stays two rows. ewlc-ap-state-registered is up. A stale sample is offline.
    """
    _auth(stack)

    def prom(_client, query):
        if "ie_wlc_ap_info" in query:
            return [
                {"metric": {"__name__": "ie_wlc_ap_info", "ap": "00:c8:8b:c1:7e:90", "ap_name": "00:c8:8b:c1:7e:90", "mac": "00:c8:8b:c1:7e:90", "ip": "10.1.1.1", "wlc": "OiOB-Bree-WLC01", "source": "OiOB-Bree-WLC01"}, "value": [NOW, "1"]},
                {"metric": {"__name__": "ie_wlc_ap_info", "ap": "AP0035.1a09.5274", "ap_name": "AP0035.1a09.5274", "mac": "00:c8:8b:c1:7e:90", "ip": "10.1.1.9", "wlc": "OiOB-Bree-WLC01"}, "value": [NOW, "1"]},
                {"metric": {"__name__": "ie_wlc_ap_info", "ap": "AP0035.1a09.5274", "ap_name": "AP0035.1a09.5274", "mac": "00c8.8bc1.7e91", "ip": "10.8.0.10", "wlc": "OiOB-Bree-WLC01"}, "value": [NOW, "1"]},
                {"metric": {"__name__": "ie_wlc_ap_info", "ap": "AP-REG", "ap_name": "AP-REG", "mac": "11:22:33:44:55:66", "ap_operation_state": "ewlc-ap-state-registered", "wlc": "OiOB-Bree-WLC01"}, "value": [NOW, "1"]},
                {"metric": {"__name__": "ie_wlc_ap_info", "ap": "AP-OLD", "ap_name": "AP-OLD", "mac": "22:22:33:44:55:66", "wlc": "OiOB-Bree-WLC01"}, "value": [NOW - 3600, "1"]},
                {"metric": {"__name__": "ie_wlc_ap_info", "ap": "AP-DOWN", "ap_name": "AP-DOWN", "mac": "33:22:33:44:55:66", "ap_state/ap_operation_state": "ewlc-ap-state-deregistered", "wlc": "OiOB-Bree-WLC01"}, "value": [NOW, "1"]},
            ]
        if query.startswith("ie_wlc_radio_channel ") or query == "ie_wlc_radio_channel":
            return [{"metric": {"__name__": "ie_wlc_radio_channel", "ap": "radio-only", "wlc": "wlc-a", "radio": "1"}, "value": [NOW, "36"]}]
        if "ie_wlc_ap_oper_up" in query and "radio" not in query:
            return [{"metric": {"__name__": "ie_wlc_ap_oper_up", "ap_name": "ap-1", "wlc": "aireos"}, "value": [NOW, "1"]}]
        return []

    stack["fleet"]._prom = prom
    stack["fleet"].cache.drop("ap-snapshot")
    body = stack["client"].get("/api/v1/access-points?page=1&page_size=50")
    assert body.status_code == 200, body.text
    rows = { (row["name"], row["mac"]): row["status"] for row in body.json()["rows"] }
    assert rows[("AP0035.1a09.5274", "00:c8:8b:c1:7e:90")] == "up"
    assert ("00:c8:8b:c1:7e:90", "00:c8:8b:c1:7e:90") not in rows
    assert any(name == "AP0035.1a09.5274" and mac != "00:c8:8b:c1:7e:90" and status == "up" for (name, mac), status in rows.items())
    assert rows[("AP-REG", "11:22:33:44:55:66")] == "up"
    assert rows[("AP-OLD", "22:22:33:44:55:66")] == "down"
    assert rows[("AP-DOWN", "33:22:33:44:55:66")] == "down"
    assert rows[("radio-only", "")] == "up"
    assert rows[("ap-1", "")] == "up"
