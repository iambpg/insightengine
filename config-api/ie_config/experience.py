"""Service experience: generated device config and the UI summary.

Config text is for an operator to paste. Nothing in this module connects
to a router or a controller to push it.

Catalyst 9800 wireless detail is model-driven telemetry. AireOS stays on
SNMP. cEdge tunnel loss, latency and jitter are MDT (Cisco-IOS-XE-sdwan-oper).
CISCO-IETF-BFD-MIB is only session up/down. IP SLA to the site VBS server is
collected later by snmp-exporter (CISCO-RTTMON-MIB).
"""

from __future__ import annotations

import importlib.util
import os
import zlib
from pathlib import Path
from urllib.parse import quote

import httpx

from .errors import ApiError
from .fleet import UpstreamError, netbox_headers
from .health import classify_profile

_CATALOG = None


def wlc_catalog():
    global _CATALOG
    if _CATALOG is None:
        path = Path(__file__).resolve().parents[2] / "config" / "telegraf" / "wlc" / "catalog.py"
        spec = importlib.util.spec_from_file_location("wlc_catalog", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _CATALOG = module
    return _CATALOG

NOT_CONFIGURED = "not configured"
PUSHED = False
PERIOD_CS = 6000  # 60 seconds. IOS-XE periodic is centiseconds. 30s is 3000.


def _blob(*parts: str) -> str:
    return " ".join(str(part or "") for part in parts).lower()


def is_cedge(role: str = "", platform: str = "", manufacturer: str = "", model: str = "") -> bool:
    """Cisco IOS-XE SD-WAN edge. The FortiGate role `sdwan` is not a cEdge."""
    text = _blob(role, platform, manufacturer, model)
    if any(token in text for token in ("forti", "fortigate", "palo", "asa")):
        return False
    role_l = (role or "").strip().lower().replace("_", "-")
    plat = (platform or "").strip().lower().replace("_", "-")
    if role_l in ("cedge", "sdwan-edge", "wan-edge"):
        return True
    if plat in ("ios-xe-sdwan", "iosxe-sdwan", "cedge"):
        return True
    return False


def is_iosxe_wlc(role: str = "", platform: str = "", manufacturer: str = "", model: str = "") -> bool:
    return classify_profile(role, platform, manufacturer, model) == "iosxe-wlc"


def is_aireos(role: str = "", platform: str = "", manufacturer: str = "", model: str = "") -> bool:
    return classify_profile(role, platform, manufacturer, model) == "aireos"


def sla_candidate(role: str = "", platform: str = "", manufacturer: str = "", model: str = "") -> bool:
    """Cisco IOS or IOS-XE router or switch. Not a WLC, AP, firewall or cEdge-only box.

    cEdge is included: it is IOS-XE and can run IP SLA toward the VBS server.
    """
    profile = classify_profile(role, platform, manufacturer, model)
    return profile in ("ios", "iosxe") or is_cedge(role, platform, manufacturer, model)


def _id_block(name: str, span: int, origin: int) -> int:
    slot = zlib.crc32((name or "device").encode("utf-8")) % span
    return origin + slot * 10


def telemetry_ids(name: str) -> int:
    return _id_block(name, 3000, 60000)


def sla_ids(name: str) -> int:
    return _id_block(name, 4000, 10000)


def _receiver(explicit: str | None = None) -> tuple[str, int, bool]:
    host = (explicit if explicit is not None else os.environ.get("IE_MDT_RECEIVER") or "").strip()
    raw_port = (os.environ.get("IE_MDT_PORT") or "57500").strip()
    try:
        port = int(raw_port)
    except ValueError:
        port = 57500
    if port < 1 or port > 65535:
        port = 57500
    return host, port, bool(host)


def _sub(number: int, xpath: str, source: str, receiver: str, port: int, policy: str) -> list[str]:
    lines = [
        "telemetry ietf subscription %d" % number,
        " encoding encode-kvgpb",
        " filter xpath %s" % xpath,
        " source-address %s" % source,
        " stream yang-push",
        " update-policy %s" % policy,
        " receiver ip address %s %d protocol grpc-tcp" % (receiver, port),
    ]
    return lines


def telemetry_config(device: dict, receiver: str | None = None) -> dict:
    """Paste-only controller config. Not pushed."""
    name = str(device.get("name") or device.get("hostname") or "device")
    ip = str(device.get("ip") or device.get("mgmtIp") or "").split("/")[0]
    role = str(device.get("role") or "")
    platform = str(device.get("platform") or "")
    manufacturer = str(device.get("manufacturer") or "")
    model = str(device.get("model") or device.get("modelFamily") or "")
    host, port, receiver_set = _receiver(receiver)
    shown = host or "10.255.255.1"
    user = wlc_catalog().snmp_username(dict(os.environ))
    base = {
        "pushed": PUSHED,
        "title": "Controller config",
        "filename": "controller-config.txt",
        "receiverConfigured": receiver_set,
        "transport": (os.environ.get("IE_WLC_MDT_TRANSPORT") or "grpc").strip().lower() or "grpc",
    }
    if is_aireos(role, platform, manufacturer, model):
        return dict(base, configured=True, reason="", config=wlc_catalog().aireos_snmp_config(name, user))
    wlc = is_iosxe_wlc(role, platform, manufacturer, model)
    cedge = is_cedge(role, platform, manufacturer, model)
    if not wlc and not cedge:
        return dict(base, configured=False, reason=(
            "Controller config is generated for a Catalyst 9800, an AireOS WLC, or a Cisco "
            "SD-WAN cEdge (role cedge, sdwan-edge, wan-edge, or platform ios-xe-sdwan)."
        ), config="")
    if not ip:
        return dict(base, configured=False, reason="This device has no management IP for source-address.", config="")
    if wlc:
        if not receiver_set:
            # The placeholder is already called out inside the generated text.
            pass
        return dict(base, configured=True, reason="", config=wlc_catalog().iosxe_wlc_config(name, ip, shown, port, user))
    ids = telemetry_ids(name)
    lines = [
        "! Generated by InsightEngine for %s. Paste on the device." % name,
        "! InsightEngine does not push this configuration.",
        "! Periodic interval %d centiseconds is 60 seconds. On-change is used where the leaf is event-driven." % PERIOD_CS,
        "! gNMI dial-in is an alternative: set IE_WLC_MDT_TRANSPORT=gnmi on telegraf-wlc.",
        "! Do not enable dial-out and dial-in for the same paths.",
    ]
    if not receiver_set:
        lines.append("! IE_MDT_RECEIVER is unset. Replace %s with the IP the device uses to reach telegraf-wlc." % shown)
    lines.append("!")
    lines.append("! Cisco-IOS-XE-sdwan-oper. Loss, latency and jitter are per tunnel and color.")
    lines.append("! SNMP CISCO-IETF-BFD-MIB has session up/down only, not these three.")
    pairs = [
        (0, "/sdwan-oper:sdwan-oper-data/bfd/sessions", "periodic %d" % PERIOD_CS),
        (1, "/sdwan-oper:sdwan-oper-data/bfd/sessions", "on-change"),
        (2, "/sdwan-oper:sdwan-oper-data/app-route/statistics", "periodic %d" % PERIOD_CS),
    ]
    for offset, xpath, policy in pairs:
        lines.extend(_sub(ids + offset, xpath, ip, shown, port, policy))
        lines.append("!")
    return dict(base, configured=True, reason="", config="\n".join(lines).rstrip() + "\n")


def _port(value, default: int = 9999) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return default
    if port < 1 or port > 65535:
        return default
    return port


def ip_sla_config(device: dict, site: dict | None) -> dict:
    """Cisco IOS IP SLA toward the site VBS server. Not pushed."""
    name = str(device.get("name") or device.get("hostname") or "device")
    ip = str(device.get("ip") or device.get("mgmtIp") or "").split("/")[0]
    role = str(device.get("role") or "")
    platform = str(device.get("platform") or "")
    manufacturer = str(device.get("manufacturer") or "")
    model = str(device.get("model") or device.get("modelFamily") or "")
    base = {"pushed": PUSHED, "title": "IP SLA config", "filename": "ip-sla.txt"}
    if not sla_candidate(role, platform, manufacturer, model):
        return dict(base, configured=False, reason=(
            "IP SLA config is generated for Cisco IOS and IOS-XE. "
            "This device is %s." % (classify_profile(role, platform, manufacturer, model))
        ), config="")
    site = site or {}
    target = str(site.get("vbs_server_ip") or "").strip()
    if not target:
        site_name = str(site.get("name") or device.get("site") or "this site")
        return dict(base, configured=False, reason=(
            "not configured. Site %s has no vbs_server_ip. "
            "Set the site custom fields vbs_server_ip and vbs_server_port." % site_name
        ), config="")
    if not ip:
        return dict(base, configured=False, reason="This device has no management IP to use as source-ip.", config="")
    port = _port(site.get("vbs_server_port"), 9999)
    ids = sla_ids(name)
    profile = classify_profile(role, platform, manufacturer, model)
    jitter = profile in ("ios", "iosxe") or is_cedge(role, platform, manufacturer, model)
    lines = [
        "! Generated by InsightEngine for %s. Paste on the router." % name,
        "! InsightEngine does not push this configuration.",
        "! Target %s port %d is the site VBS server." % (target, port),
        "ip sla %d" % ids,
        " tcp-connect %s %d source-ip %s" % (target, port, ip),
        " timeout 2000",
        " frequency 60",
        "ip sla schedule %d life forever start-time now" % ids,
    ]
    if jitter:
        lines.extend([
            "!",
            "! udp-jitter needs a UDP responder on the VBS server at this port.",
            "! icmp-jitter does not. IOS-XE supports both. Classic IOS needs 12.4(4)T or later for icmp-jitter.",
            "! Omit a block the image rejects.",
            "ip sla %d" % (ids + 1),
            " udp-jitter %s %d source-ip %s num-packets 20" % (target, port, ip),
            " timeout 2000",
            " frequency 60",
            "ip sla schedule %d life forever start-time now" % (ids + 1),
            "ip sla %d" % (ids + 2),
            " icmp-jitter %s source-ip %s num-packets 20" % (target, ip),
            " frequency 60",
            "ip sla schedule %d life forever start-time now" % (ids + 2),
        ])
    lines.append("!")
    return dict(base, configured=True, reason="", config="\n".join(lines).rstrip() + "\n")


def _section(configured: bool, reason: str, **extra) -> dict:
    body = {"configured": configured, "reason": "" if configured else reason}
    body.update(extra)
    return body


def build_experience(devices: list[dict], sites: list[dict], services: list[dict], metrics: dict | None = None) -> dict:
    """Inventory plus optional Prometheus samples. Empty groups say not configured."""
    metrics = metrics or {}
    wlcs = []
    edges = []
    for device in devices:
        role = str(device.get("role") or "")
        platform = str(device.get("platform") or "")
        manufacturer = str(device.get("manufacturer") or "")
        model = str(device.get("model") or "")
        row = {
            "name": str(device.get("name") or ""),
            "site": str(device.get("site") or ""),
            "platform": platform,
            "role": role,
            "ip": str(device.get("ip") or ""),
        }
        if is_iosxe_wlc(role, platform, manufacturer, model) or is_aireos(role, platform, manufacturer, model):
            row["transport"] = "mdt" if is_iosxe_wlc(role, platform, manufacturer, model) else "snmp"
            wlcs.append(row)
        elif is_cedge(role, platform, manufacturer, model):
            row["transport"] = "mdt"
            edges.append(row)
    vbs_sites = []
    for site in sites:
        ip = str(site.get("vbs_server_ip") or "").strip()
        if not ip:
            continue
        vbs_sites.append({
            "name": str(site.get("name") or ""),
            "vbsServerIp": ip,
            "vbsServerPort": _port(site.get("vbs_server_port"), 9999),
        })
    targets = []
    for service in services:
        tags = [str(tag).lower() for tag in (service.get("tags") or [])]
        kind = "bank" if "bank" in tags else "third-party" if "third-party" in tags else ""
        if not kind:
            continue
        probe = str(service.get("probe") or "").strip().lower()
        targets.append({
            "name": str(service.get("name") or ""),
            "site": str(service.get("site") or ""),
            "kind": kind,
            "probe": probe or NOT_CONFIGURED,
            "address": str(service.get("address") or ""),
            "port": service.get("port") or "",
        })
    radios = list(metrics.get("radios") or [])[:50]
    tunnels = list(metrics.get("tunnels") or [])[:50]
    sla = list(metrics.get("sla") or [])[:50]
    probes = list(metrics.get("probes") or [])[:50]
    return {
        "isExampleData": False,
        "degraded": list(metrics.get("degraded") or []),
        "wlc": _section(
            bool(wlcs),
            "not configured. No wireless controller is in NetBox.",
            note="Catalyst 9800 AP and client detail is MDT. AireOS stays on Telegraf SNMP. snmp-exporter keeps chassis health and the joined-AP count.",
            controllers=wlcs,
            radios=radios,
        ),
        "sdwan": _section(
            bool(edges),
            "not configured. No Cisco SD-WAN cEdge is in NetBox. Use role cedge, sdwan-edge or wan-edge, or platform ios-xe-sdwan. The FortiGate sdwan role is not this.",
            note="Loss, latency and jitter come from Cisco-IOS-XE-sdwan-oper (MDT), labelled by local and remote color. SNMP session state is CISCO-IETF-BFD-MIB.",
            routers=edges,
            tunnels=tunnels,
        ),
        "vbs": _section(
            bool(vbs_sites),
            "not configured. No site has vbs_server_ip.",
            note="IP SLA on the site router (tcp-connect, plus udp-jitter and icmp-jitter where the image supports them) and a blackbox ICMP probe.",
            sites=vbs_sites,
            sla=sla,
        ),
        "thirdParties": _section(
            bool(targets),
            "not configured. No NetBox service is tagged third-party or bank.",
            note="Tag a service third-party or bank, set custom field probe to icmp or tcp, and set an address. No real targets are seeded.",
            targets=targets,
            probes=probes,
        ),
    }


class ExperienceService:
    def __init__(self, settings, client: httpx.Client | None = None):
        self.settings = settings
        self._client = client

    def _session(self):
        if self._client is not None:
            return self._client
        return httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0))

    def _headers(self) -> dict:
        headers = netbox_headers(self.settings.netbox_token_file)
        if not headers:
            raise UpstreamError("netbox", "NetBox API token is not configured")
        return headers

    def _get(self, client, url: str):
        try:
            response = client.get(url, headers=self._headers())
        except httpx.HTTPError:
            raise UpstreamError("netbox", "NetBox is not reachable")
        if response.status_code in (401, 403):
            raise UpstreamError("netbox", "NetBox rejected the API token")
        if response.status_code == 404:
            raise ApiError(404, "not_found", "unknown device")
        if response.status_code >= 400:
            raise UpstreamError("netbox", "NetBox returned HTTP %s" % response.status_code)
        try:
            return response.json()
        except ValueError:
            raise UpstreamError("netbox", "NetBox returned a response that was not JSON")

    def _list(self, client, path: str) -> list[dict]:
        url = self.settings.netbox_url + path
        rows = []
        pages = 0
        while url and pages < 20:
            pages += 1
            body = self._get(client, url)
            if isinstance(body, list):
                return body
            rows.extend(body.get("results") or [])
            url = body.get("next") or ""
        return rows

    def summary(self) -> dict:
        degraded = []
        devices: list[dict] = []
        sites: list[dict] = []
        services: list[dict] = []
        try:
            client = self._session()
            close = self._client is None
            try:
                devices = [_device_row(row) for row in self._list(client, "/api/dcim/devices/?status=active&limit=200")]
                sites = [_site_row(row) for row in self._list(client, "/api/dcim/sites/?limit=200")]
                for tag in ("third-party", "bank"):
                    services.extend(
                        _service_row(row) for row in self._list(client, "/api/ipam/services/?tag=%s&limit=100" % tag)
                    )
            finally:
                if close:
                    client.close()
        except UpstreamError as exc:
            degraded.append(exc.message)
        metrics = {"degraded": degraded}
        try:
            metrics.update(_prom_metrics(self.settings.prometheus_url))
        except UpstreamError as exc:
            degraded.append(exc.message)
        metrics["degraded"] = degraded
        return build_experience(devices, sites, services, metrics)

    def device_bundle(self, device_id: str) -> tuple[dict, dict]:
        client = self._session()
        close = self._client is None
        try:
            device = self._one_device(client, device_id)
            site = {}
            site_id = device.get("siteId")
            if site_id:
                body = self._get(client, "%s/api/dcim/sites/%s/" % (self.settings.netbox_url, quote(str(site_id))))
                site = _site_row(body)
            elif device.get("site"):
                found = self._list(client, "/api/dcim/sites/?name=%s&limit=5" % quote(str(device["site"])))
                if found:
                    site = _site_row(found[0])
            return device, site
        finally:
            if close:
                client.close()

    def _one_device(self, client, device_id: str) -> dict:
        token = str(device_id or "").strip()
        if not token:
            raise ApiError(404, "not_found", "unknown device")
        if token.isdigit():
            body = self._get(client, "%s/api/dcim/devices/%s/" % (self.settings.netbox_url, token))
            return _device_row(body)
        found = self._list(client, "/api/dcim/devices/?name=%s&limit=5" % quote(token))
        for row in found:
            if str(row.get("name") or "") == token:
                return _device_row(row)
        if found:
            return _device_row(found[0])
        raise ApiError(404, "not_found", "unknown device")

    def ip_sla(self, device_id: str) -> dict:
        try:
            device, site = self.device_bundle(device_id)
        except UpstreamError as exc:
            raise ApiError(502, "upstream_unavailable", exc.message, {"upstream": exc.upstream})
        return ip_sla_config(device, site)

    def telemetry(self, device_id: str) -> dict:
        try:
            device, _site = self.device_bundle(device_id)
        except UpstreamError as exc:
            raise ApiError(502, "upstream_unavailable", exc.message, {"upstream": exc.upstream})
        return telemetry_config(device)


def _nested_name(value) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or value.get("slug") or "")
    return "" if value is None else str(value)


def _nested_id(value):
    if isinstance(value, dict):
        return value.get("id")
    return None


def _addr(value) -> str:
    if isinstance(value, dict):
        address = value.get("address") or ""
        return str(address).split("/")[0]
    return ""


def _device_row(raw: dict) -> dict:
    custom = raw.get("custom_fields") or {}
    role = raw.get("role") if isinstance(raw.get("role"), dict) else {}
    platform = raw.get("platform") if isinstance(raw.get("platform"), dict) else {}
    dtype = raw.get("device_type") if isinstance(raw.get("device_type"), dict) else {}
    manufacturer = dtype.get("manufacturer") if isinstance(dtype.get("manufacturer"), dict) else {}
    site = raw.get("site") if isinstance(raw.get("site"), dict) else {}
    return {
        "id": raw.get("id"),
        "name": str(raw.get("name") or ""),
        "role": str(role.get("slug") or _nested_name(raw.get("role"))),
        "platform": str(platform.get("slug") or _nested_name(raw.get("platform"))),
        "manufacturer": str(manufacturer.get("slug") or manufacturer.get("name") or ""),
        "model": str(dtype.get("model") or ""),
        "ip": _addr(raw.get("primary_ip4")) or str(custom.get("target") or ""),
        "site": str(site.get("name") or _nested_name(raw.get("site"))),
        "siteId": site.get("id") or _nested_id(raw.get("site")),
    }


def _site_row(raw: dict) -> dict:
    custom = raw.get("custom_fields") or {}
    return {
        "id": raw.get("id"),
        "name": str(raw.get("name") or ""),
        "vbs_server_ip": str(custom.get("vbs_server_ip") or "").strip(),
        "vbs_server_port": custom.get("vbs_server_port"),
    }


def _service_row(raw: dict) -> dict:
    custom = raw.get("custom_fields") or {}
    tags = []
    for tag in raw.get("tags") or []:
        if isinstance(tag, dict):
            tags.append(str(tag.get("slug") or tag.get("name") or ""))
        else:
            tags.append(str(tag))
    ports = raw.get("ports") or []
    parent = raw.get("parent") if isinstance(raw.get("parent"), dict) else {}
    address = str(custom.get("target") or "").strip()
    if not address:
        address = _addr(parent.get("primary_ip4") if isinstance(parent, dict) else None)
    site = ""
    if isinstance(parent, dict):
        site = _nested_name(parent.get("site"))
    return {
        "name": str(raw.get("name") or ""),
        "tags": tags,
        "probe": str(custom.get("probe") or ""),
        "address": address,
        "port": ports[0] if ports else "",
        "site": site,
    }


def _prom_metrics(base: str) -> dict:
    if not base:
        return {}
    queries = {
        "radios": "ie_wlc_client_radio_rssi_avg",
        "tunnels": "ie_sdwan_tunnel_loss_ratio",
        "sla": "rttMonLatestRttOperCompletionTime",
        "probes": 'probe_success{job=~"blackbox-(third-party|bank|vbs).*"}',
    }
    out = {"radios": [], "tunnels": [], "sla": [], "probes": []}
    try:
        client = httpx.Client(timeout=httpx.Timeout(8.0, connect=3.0))
    except Exception:
        raise UpstreamError("prometheus", "Prometheus is not reachable")
    try:
        for key, query in queries.items():
            try:
                response = client.get(base.rstrip("/") + "/api/v1/query", params={"query": query})
            except httpx.HTTPError:
                raise UpstreamError("prometheus", "Prometheus is not reachable")
            if response.status_code >= 500:
                raise UpstreamError("prometheus", "Prometheus returned HTTP %s" % response.status_code)
            if response.status_code >= 400:
                continue
            try:
                body = response.json()
            except ValueError:
                continue
            for item in ((body.get("data") or {}).get("result") or [])[:50]:
                metric = item.get("metric") or {}
                value = item.get("value") or [None, None]
                sample = dict(metric)
                sample["value"] = value[1] if len(value) > 1 else None
                out[key].append(sample)
    finally:
        client.close()
    return out


def mount_experience(app, user_of) -> None:
    def service() -> ExperienceService:
        current = getattr(app.state, "experience", None)
        if current is None:
            current = ExperienceService(app.state.settings)
            app.state.experience = current
        return current

    def reader(request):
        user, _csrf = user_of(request)
        return user

    @app.get("/api/v1/experience")
    def experience(request):
        reader(request)
        return service().summary()

    @app.get("/api/v1/devices/{device_id}/ip-sla-config")
    def ip_sla(device_id: str, request):
        reader(request)
        return service().ip_sla(device_id)

    @app.get("/api/v1/devices/{device_id}/telemetry-config")
    def telemetry(device_id: str, request):
        reader(request)
        return service().telemetry(device_id)
