"""Public links for the stack's web UIs.

Ports and the host come from the environment ie-config already receives
(PUBLIC_HOST and PORT_*). Health is probed on the Docker network. The
response contains no secrets.
"""

from __future__ import annotations

import os

import httpx
from fastapi import Request

# id, name, port env, default port, public scheme, internal health URL.
# InsightEngine itself is the UI published on PORT_HTTPS.
# Host ports: NetBox 8092, Alertmanager 8086. SNMP, blackbox, and Telegraf are plain HTTP.
# Health URLs stay on the container ports (NetBox 8080, Alertmanager 9093).
_APPS = (
    ("ui", "InsightEngine", "PORT_HTTPS", "443", "https", "http://insightengine-ui:8080/healthz"),
    ("netbox", "NetBox", "PORT_NETBOX", "8092", "https", "http://netbox:8080/api/status/"),
    ("grafana", "Grafana", "PORT_GRAFANA", "3000", "https", "http://grafana:3000/api/health"),
    ("prometheus", "Prometheus", "PORT_PROMETHEUS", "9090", "https", "http://prometheus:9090/-/healthy"),
    ("alertmanager", "Alertmanager", "PORT_ALERTMANAGER", "8086", "https", "http://alertmanager:9093/-/healthy"),
    ("activepieces", "Activepieces", "PORT_ACTIVEPIECES", "8081", "https", "http://activepieces-app/"),
    ("netdisco", "Netdisco", "PORT_NETDISCO", "5000", "https", "http://netdisco-web:5000/"),
    ("oxidized", "Oxidized", "PORT_OXIDIZED", "8888", "https", "http://oxidized:8888/nodes"),
    ("snmp-exporter", "SNMP exporter", "PORT_SNMP_EXPORTER", "9116", "http", "http://snmp-exporter-1:9116/-/healthy"),
    ("blackbox", "blackbox exporter", "PORT_BLACKBOX", "9115", "http", "http://blackbox-exporter-1:9115/-/healthy"),
    ("telegraf", "Telegraf", "PORT_TELEGRAF", "57500", "http", "http://telegraf-host:9273/metrics"),
)


def public_base(host: str, port: str, scheme: str = "https") -> str:
    host = (host or "").strip()
    if scheme not in ("http", "https"):
        scheme = "https"
    if not host or any(char in host for char in " \t/:@\\"):
        return ""
    digits = str(port or "").strip()
    if not digits.isdigit() or not (1 <= int(digits) <= 65535):
        return ""
    if scheme == "https" and digits == "443":
        return "https://%s/" % host
    if scheme == "http" and digits == "80":
        return "http://%s/" % host
    return "%s://%s:%s/" % (scheme, host, digits)


def _port(name: str, default: str) -> str:
    raw = os.environ.get(name, "").strip()
    return raw or default


def _probe(client: httpx.Client, url: str) -> str:
    try:
        response = client.get(url)
    except httpx.HTTPError:
        return "down"
    if response.status_code < 500:
        return "up"
    return "down"


def build_catalog(host: str, role: str, client: httpx.Client | None = None) -> dict:
    own = client or httpx.Client(timeout=httpx.Timeout(2.0, connect=1.0), follow_redirects=True)
    close = client is None
    apps = []
    try:
        for app_id, name, env_name, default, scheme, health in _APPS:
            url = public_base(host, _port(env_name, default), scheme)
            status = _probe(own, health) if url else "unknown"
            apps.append({"id": app_id, "name": name, "url": url, "status": status})
    finally:
        if close:
            own.close()
    return {"host": host, "role": role, "apps": apps}


def mount_apps_launcher(app, user_of, client: httpx.Client | None = None) -> None:
    @app.get("/api/v1/apps/launcher")
    def launcher(request: Request):
        user, _csrf = user_of(request)
        host = getattr(app.state.settings, "public_host", "") or ""
        return build_catalog(host, getattr(user, "role", "") or "", client)
