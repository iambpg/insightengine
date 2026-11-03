"""Read Netdisco, NetBox, FortiManager, and Nominatim.

NetBox writes go through the existing NetBoxWriter. This module has no delete
call. Secret values are not logged.
"""

from __future__ import annotations

import logging
import os
import time

import httpx

from ie_config.discovery import NetBoxWriter
from ie_config.fleet import netbox_headers
from ie_config.hostnames import effective_suffixes

log = logging.getLogger("ie-config.netbridge")

_PLACEHOLDER = "unset-placeholder"
_LAST_GEO = 0.0


def suffixes_for(settings) -> list[str]:
    return effective_suffixes(settings)


def load_netdisco(database_url: str) -> dict:
    empty = {"ok": False, "message": "Netdisco is not configured", "devices": [], "modules": [], "addresses": []}
    if not database_url:
        return empty
    try:
        import psycopg
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT host(ip)::text, COALESCE(dns, ''), COALESCE(name, ''), "
                    "COALESCE(description, ''), COALESCE(vendor, ''), COALESCE(model, ''), "
                    "COALESCE(serial, ''), COALESCE(location, '') FROM device"
                )
                devices = [{
                    "ip": ip or "",
                    "dns": dns or "",
                    "name": name or dns or "",
                    "description": descr or "",
                    "vendor": vendor or "",
                    "model": model or "",
                    "serial": serial or "",
                    "location": location or "",
                } for ip, dns, name, descr, vendor, model, serial, location in cur.fetchall()]
                modules = _modules(cur)
                addresses = _addresses(cur)
    except Exception:
        log.warning("netdisco read failed")
        return {"ok": False, "message": "Netdisco could not be read", "devices": [], "modules": [], "addresses": []}
    return {"ok": True, "message": "", "devices": devices, "modules": modules, "addresses": addresses}


def _modules(cur) -> list[dict]:
    try:
        cur.execute(
            "SELECT host(ip)::text, COALESCE(index, 0), COALESCE(name, ''), COALESCE(class, ''), "
            "COALESCE(pos, 0), COALESCE(serial, ''), COALESCE(model, ''), COALESCE(description, '') "
            "FROM device_module"
        )
        rows = cur.fetchall()
    except Exception:
        return []
    return [{
        "ip": ip or "",
        "index": int(index or 0),
        "name": name or "",
        "class": kind or "",
        "pos": int(pos or 0),
        "serial": serial or "",
        "model": model or "",
        "description": descr or "",
    } for ip, index, name, kind, pos, serial, model, descr in rows]


def _addresses(cur) -> list[dict]:
    try:
        cur.execute(
            "SELECT host(ip)::text, host(alias)::text, COALESCE(port, ''), COALESCE(dns, '') "
            "FROM device_ip WHERE family(alias) = 4"
        )
        rows = cur.fetchall()
    except Exception:
        return []
    return [{
        "device_ip": ip or "",
        "address": alias or "",
        "port": port or "",
        "dns": dns or "",
    } for ip, alias, port, dns in rows]


def _writer(settings) -> NetBoxWriter:
    headers = netbox_headers(settings.netbox_token_file)
    if not headers:
        raise RuntimeError("netbox_token")
    return NetBoxWriter(settings.netbox_url, headers)


def _get_all(settings, path: str, cap: int = 50000) -> list[dict]:
    writer = _writer(settings)
    rows: list[dict] = []
    offset = 0
    while len(rows) < cap:
        sep = "&" if "?" in path else "?"
        page = writer._req("GET", "%s%slimit=200&offset=%s" % (path, sep, offset))
        chunk = page.get("results") or []
        rows.extend(chunk)
        if not chunk or not page.get("next"):
            break
        offset += len(chunk)
    return rows


def netbox_device(raw: dict) -> dict:
    site = raw.get("site") if isinstance(raw.get("site"), dict) else {}
    role = raw.get("role") if isinstance(raw.get("role"), dict) else {}
    rack = raw.get("rack") if isinstance(raw.get("rack"), dict) else {}
    vc = raw.get("virtual_chassis") if isinstance(raw.get("virtual_chassis"), dict) else {}
    dtype = raw.get("device_type") if isinstance(raw.get("device_type"), dict) else {}
    manufacturer = dtype.get("manufacturer") if isinstance(dtype.get("manufacturer"), dict) else {}
    platform = raw.get("platform") if isinstance(raw.get("platform"), dict) else {}
    primary = raw.get("primary_ip4") if isinstance(raw.get("primary_ip4"), dict) else {}
    address = str(primary.get("address") or "").split("/")[0]
    return {
        "id": raw.get("id"),
        "name": raw.get("name") or "",
        "serial": raw.get("serial") or "",
        "ip": address,
        "primary_set": bool(primary.get("id")),
        "site": site.get("name") or "",
        "site_id": site.get("id"),
        "role": role.get("name") or "",
        "role_slug": role.get("slug") or "",
        "role_id": role.get("id"),
        "rack_id": rack.get("id"),
        "vc_id": vc.get("id"),
        "vc_position": raw.get("vc_position"),
        "model": dtype.get("model") or "",
        "part": (raw.get("part_number") or dtype.get("part_number") or ""),
        "manufacturer": manufacturer.get("name") or "",
        "platform": platform.get("name") or "",
        "custom_fields": raw.get("custom_fields") if isinstance(raw.get("custom_fields"), dict) else {},
    }


def load_netbox_devices(settings) -> list[dict]:
    try:
        raws = _get_all(settings, "/api/dcim/devices/?status=active")
    except Exception:
        log.warning("netbox device list failed")
        return []
    return [netbox_device(raw) for raw in raws]


def load_netbox_sites(settings) -> list[dict]:
    try:
        raws = _get_all(settings, "/api/dcim/sites/")
    except Exception:
        log.warning("netbox site list failed")
        return []
    sites = []
    for raw in raws:
        region = raw.get("region") if isinstance(raw.get("region"), dict) else {}
        custom = raw.get("custom_fields") if isinstance(raw.get("custom_fields"), dict) else {}
        country = str(custom.get("country") or "")
        code = str(custom.get("country_code") or "")
        sites.append({
            "id": raw.get("id"),
            "name": raw.get("name") or "",
            "latitude": raw.get("latitude"),
            "longitude": raw.get("longitude"),
            "region": region.get("name") or "",
            "country": country,
            "country_code": code,
            "address": raw.get("physical_address") or "",
        })
    return sites


def load_ip_index(settings) -> dict:
    """address -> {device_id, interface, device}. Failures yield an empty index."""
    try:
        raws = _get_all(settings, "/api/ipam/ip-addresses/")
    except Exception:
        log.warning("netbox address list failed")
        return {}
    found = {}
    for raw in raws:
        address = str(raw.get("address") or "").split("/")[0]
        if not address:
            continue
        assigned = raw.get("assigned_object") if isinstance(raw.get("assigned_object"), dict) else {}
        device = assigned.get("device") if isinstance(assigned.get("device"), dict) else {}
        found[address] = {
            "device_id": device.get("id"),
            "device": device.get("name") or "",
            "interface": assigned.get("name") or "",
        }
    return found


def community_for(settings, ip: str) -> str:
    """v2c community for an address. Profile assignment wins, then the env community."""
    path = os.path.join(getattr(settings, "config_root", "") or "", "data", "snmp", "assignments.json")
    try:
        import json
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        data = {}
    for group in (data.get("groups") or []) if isinstance(data, dict) else []:
        if not isinstance(group, dict):
            continue
        if ip and ip in (group.get("ips") or []) and group.get("version") == "2c" and group.get("community"):
            return str(group["community"])
    community = (os.environ.get("SNMP_V2_COMMUNITY") or "").strip()
    if not community or community == _PLACEHOLDER:
        return ""
    return community


def wlc_file(settings) -> list[dict]:
    path = os.path.join(getattr(settings, "config_root", "") or "", "config", "discovery", "wlc-targets.yml")
    if not os.path.isfile(path):
        return []
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
    except Exception:
        return []
    rows = loaded.get("targets") if isinstance(loaded, dict) else None
    if not isinstance(rows, list):
        return []
    out = []
    for row in rows:
        if isinstance(row, dict) and (row.get("ip") or row.get("name")):
            out.append({
                "ip": str(row.get("ip") or ""),
                "name": str(row.get("name") or row.get("ip") or ""),
                "platform": str(row.get("platform") or ""),
                "model": str(row.get("model") or ""),
                "serial": str(row.get("serial") or ""),
                "vendor": "Cisco",
            })
    return out


def fmg_list(url: str, token: str, http: httpx.Client | None = None) -> dict:
    if not url or not token:
        return {
            "ok": False,
            "configured": False,
            "message": "FortiManager URL and token are not configured. Add them in Settings → Vault.",
            "instances": [],
            "devices": [],
        }
    base = url.rstrip("/")
    body = {
        "id": 1,
        "method": "get",
        "params": [{"url": "/dvmdb/device"}],
    }
    client = http or httpx.Client(timeout=30.0)
    try:
        response = client.post(
            base + "/jsonrpc",
            json=body,
            headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
        )
    except httpx.HTTPError:
        log.warning("fortimanager request failed")
        return {"ok": False, "configured": True, "message": "FortiManager did not answer", "instances": [], "devices": []}
    finally:
        if http is None:
            client.close()
    if response.status_code >= 400:
        log.warning("fortimanager status %s", response.status_code)
        return {"ok": False, "configured": True, "message": "FortiManager rejected the token", "instances": [], "devices": []}
    try:
        payload = response.json()
    except ValueError:
        return {"ok": False, "configured": True, "message": "FortiManager returned a response that was not JSON", "instances": [], "devices": []}
    result = payload.get("result") if isinstance(payload, dict) else None
    data = []
    if isinstance(result, list) and result:
        first = result[0] if isinstance(result[0], dict) else {}
        data = first.get("data") or []
    elif isinstance(result, dict):
        data = result.get("data") or []
    devices = []
    if isinstance(data, dict):
        data = [data]
    for row in data if isinstance(data, list) else []:
        if not isinstance(row, dict):
            continue
        ip = row.get("ip") or row.get("mgmt_ip") or ""
        if isinstance(ip, list):
            ip = ip[0] if ip else ""
        devices.append({
            "name": str(row.get("name") or row.get("hostname") or ""),
            "serial": str(row.get("sn") or row.get("serial") or ""),
            "ip": str(ip or "").split("/")[0],
            "platform": str(row.get("platform_str") or row.get("os_type") or row.get("platform") or ""),
            "adom": str(row.get("adom") or "root"),
        })
    host = base.split("://", 1)[-1].split("/")[0]
    return {
        "ok": True,
        "configured": True,
        "message": "",
        "instances": [{"name": host, "devices": len(devices)}],
        "devices": devices,
    }


def nominatim(query: str, country_code: str = "", http: httpx.Client | None = None, pause: float = 1.1) -> dict | None:
    global _LAST_GEO
    if not query.strip():
        return None
    wait = pause - (time.time() - _LAST_GEO)
    if pause and wait > 0:
        time.sleep(wait)
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": "1",
        "addressdetails": "1",
    }
    if country_code and len(country_code) == 2:
        params["countrycodes"] = country_code.lower()
    headers = {"User-Agent": "InsightEngine-NetBridge/1.0 (network inventory geocode)", "Accept": "application/json"}
    client = http or httpx.Client(timeout=20.0)
    try:
        response = client.get("https://nominatim.openstreetmap.org/search", params=params, headers=headers)
    except httpx.HTTPError:
        log.warning("nominatim request failed")
        return None
    finally:
        _LAST_GEO = time.time()
        if http is None:
            client.close()
    if response.status_code >= 400:
        log.warning("nominatim status %s", response.status_code)
        return None
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, list) or not body:
        return None
    hit = body[0] if isinstance(body[0], dict) else None
    if not hit:
        return None
    address = hit.get("address") if isinstance(hit.get("address"), dict) else {}
    return {
        "lat": hit.get("lat"),
        "lon": hit.get("lon"),
        "label": hit.get("display_name") or "",
        "country": address.get("country") or "",
        "country_code": address.get("country_code") or "",
    }


def apply_changes(settings, changes: list[dict]) -> dict:
    """Run a confirmed plan. Refuses unsafe ops before any request."""
    from .plan import validate_changes
    validate_changes(changes)
    writer = _writer(settings)
    counts = {"created": 0, "updated": 0, "skipped": 0, "errors": 0}
    errors = []
    vc_ids: dict[str, int] = {}
    interfaces: dict[tuple, int] = {}
    ip_ids: dict[str, int] = {}
    for change in changes:
        try:
            op = change["op"]
            if op == "create_vc":
                vc_ids[change["name"]] = _ensure_vc(writer, change["name"])
                counts["updated"] += 1
            elif op == "create_device":
                device_id = _create_device(writer, change, vc_ids)
                if device_id:
                    counts["created"] += 1
                else:
                    counts["errors"] += 1
            elif op == "attach_vc":
                if _attach(writer, change, vc_ids):
                    counts["updated"] += 1
                else:
                    counts["skipped"] += 1
            elif op == "ensure_interface":
                iface = _ensure_interface(writer, change["device_id"], change["name"])
                interfaces[(change["device_id"], change["name"])] = iface
                counts["updated"] += 1
            elif op == "assign_ip":
                key = (change["device_id"], change["interface"])
                iface = interfaces.get(key) or _ensure_interface(writer, change["device_id"], change["interface"])
                ip_id = _assign_ip(writer, iface, change["address"])
                ip_ids[change["address"]] = ip_id
                counts["created"] += 1
            elif op == "set_primary_if_empty":
                ip_id = ip_ids.get(change["address"])
                if ip_id and _set_primary_if_empty(writer, change["device_id"], ip_id):
                    counts["updated"] += 1
                else:
                    counts["skipped"] += 1
            elif op == "set_coords":
                writer._req("PATCH", "/api/dcim/sites/%s/" % change["site_id"], {
                    "latitude": change["latitude"],
                    "longitude": change["longitude"],
                })
                counts["updated"] += 1
            elif op == "ensure_custom_field":
                _ensure_field(writer, change["name"])
            elif op == "set_custom_fields":
                _merge_fields(writer, change["device_id"], change["fields"])
                counts["updated"] += 1
            else:
                raise RuntimeError("refused")
        except Exception as exc:
            counts["errors"] += 1
            errors.append("%s: %s" % (change.get("op"), exc.__class__.__name__))
            log.warning("netbridge apply %s failed: %s", change.get("op"), exc.__class__.__name__)
    return {"counts": counts, "errors": errors[:50]}


def _ensure_vc(writer: NetBoxWriter, name: str) -> int:
    from urllib.parse import quote
    found = writer._req("GET", "/api/dcim/virtual-chassis/?name=%s" % quote(name, safe=""))
    rows = found.get("results") or []
    exact = [row for row in rows if (row.get("name") or "") == name]
    if exact:
        return int(exact[0]["id"])
    created = writer._req("POST", "/api/dcim/virtual-chassis/", {"name": name})
    return int(created["id"])


def _create_device(writer: NetBoxWriter, change: dict, vc_ids: dict[str, int]) -> int | None:
    from ie_config.discovery import _slug, manufacturer_identity
    vendor = change.get("vendor") or "Unknown"
    mfr_name, mfr_slug = manufacturer_identity(vendor, {})
    model = (change.get("model") or "unknown")[:64]
    manufacturer = writer.ensure("/api/dcim/manufacturers/", mfr_slug, {"name": mfr_name, "slug": mfr_slug})
    dtype = writer.find_device_type(manufacturer["id"], model, {})
    if dtype is None:
        model_slug = _slug(model)[:40]
        dtype = writer.ensure("/api/dcim/device-types/", model_slug, {
            "manufacturer": manufacturer["id"], "model": model, "slug": model_slug,
        })
    role_name = (change.get("role") or "Access switch").strip()
    role_slug = _slug(role_name)
    role = writer.ensure("/api/dcim/device-roles/", role_slug, {"name": role_name, "slug": role_slug, "color": "2196f3"})
    site_name = (change.get("site") or "discovered").strip()
    site_slug = _slug(site_name)
    site = writer.ensure("/api/dcim/sites/", site_slug, {"name": site_name, "slug": site_slug, "status": "active"})
    body = {
        "name": (change.get("name") or "device")[:64],
        "device_type": dtype["id"],
        "role": role["id"],
        "site": site["id"],
        "status": "active",
    }
    if change.get("serial"):
        body["serial"] = str(change["serial"])[:50]
    platform_name = (change.get("platform") or "").strip()
    if platform_name:
        platform_slug = _slug(platform_name)
        platform = writer.ensure("/api/dcim/platforms/", platform_slug, {
            "name": platform_name, "slug": platform_slug, "manufacturer": manufacturer["id"],
        })
        body["platform"] = platform["id"]
    vc_name = change.get("vc_name")
    if vc_name:
        body["virtual_chassis"] = vc_ids.get(vc_name) or _ensure_vc(writer, vc_name)
        body["vc_position"] = int(change.get("vc_position") or 1)
    created = writer._req("POST", "/api/dcim/devices/", body)
    device_id = int(created["id"])
    ip = (change.get("ip") or "").strip()
    if ip:
        try:
            iface = _ensure_interface(writer, device_id, "mgmt")
            ip_id = _assign_ip(writer, iface, ip if "/" in ip else ip + "/32")
            _set_primary_if_empty(writer, device_id, ip_id)
        except Exception:
            log.warning("netbridge address on new device failed")
    return device_id


def _attach(writer: NetBoxWriter, change: dict, vc_ids: dict[str, int]) -> bool:
    current = writer._req("GET", "/api/dcim/devices/%s/" % change["device_id"])
    if current.get("virtual_chassis"):
        return False
    vc_name = change.get("vc_name") or ""
    vc_id = vc_ids.get(vc_name) or _ensure_vc(writer, vc_name)
    # Name, site, role, and rack are not in this body.
    writer._req("PATCH", "/api/dcim/devices/%s/" % change["device_id"], {
        "virtual_chassis": vc_id,
        "vc_position": int(change.get("vc_position") or 1),
    })
    return True


def _ensure_interface(writer: NetBoxWriter, device_id, name: str) -> int:
    from urllib.parse import quote
    found = writer._req(
        "GET",
        "/api/dcim/interfaces/?device_id=%s&name=%s" % (device_id, quote(name, safe="")),
    )
    rows = found.get("results") or []
    exact = [row for row in rows if (row.get("name") or "") == name]
    if exact:
        return int(exact[0]["id"])
    created = writer._req("POST", "/api/dcim/interfaces/", {
        "device": device_id, "name": name, "type": "virtual",
    })
    return int(created["id"])


def _assign_ip(writer: NetBoxWriter, interface_id: int, address: str) -> int:
    created = writer._req("POST", "/api/ipam/ip-addresses/", {
        "address": address,
        "status": "active",
        "assigned_object_type": "dcim.interface",
        "assigned_object_id": interface_id,
        "description": "assigned by NetBridge",
    })
    return int(created["id"])


def _set_primary_if_empty(writer: NetBoxWriter, device_id, ip_id: int) -> bool:
    current = writer._req("GET", "/api/dcim/devices/%s/" % device_id)
    if current.get("primary_ip4"):
        return False
    writer._req("PATCH", "/api/dcim/devices/%s/" % device_id, {"primary_ip4": ip_id})
    return True


def _ensure_field(writer: NetBoxWriter, name: str) -> None:
    from urllib.parse import quote
    found = writer._req("GET", "/api/extras/custom-fields/?name=%s" % quote(name, safe=""))
    rows = found.get("results") or []
    if any((row.get("name") or "") == name for row in rows):
        return
    label = name.replace("eox_", "EoX ").replace("_", " ")
    writer._req("POST", "/api/extras/custom-fields/", {
        "name": name,
        "label": label,
        "type": "text",
        "object_types": ["dcim.device"],
        "required": False,
    })


def _merge_fields(writer: NetBoxWriter, device_id, fields: dict) -> None:
    current = writer._req("GET", "/api/dcim/devices/%s/" % device_id)
    custom = dict(current.get("custom_fields") or {})
    for key, value in fields.items():
        if str(key).startswith("eox_"):
            custom[key] = value
    writer._req("PATCH", "/api/dcim/devices/%s/" % device_id, {"custom_fields": custom})
