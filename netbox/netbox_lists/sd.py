"""Prometheus HTTP SD for /api/plugins/lists/prometheus-devices/.

No Django imports here so the mapping can be unit-tested without NetBox.
"""

from __future__ import annotations

import os

import yaml


def _slug(value) -> str:
    return "" if value is None else str(value)


def load_map(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _join_modules(chosen: dict, mapping: dict, custom_auth: str) -> tuple[str, str]:
    modules = chosen.get("modules") or chosen.get("module") or mapping.get("default_module") or "if_mib"
    if isinstance(modules, list):
        modules = ",".join(str(item) for item in modules if item)
    auth = custom_auth or chosen.get("auth") or mapping.get("default_auth") or "ntt_snmpv3_auth"
    return str(modules), auth


def choose_module(role: str, manufacturer: str, platform: str, custom_module: str, custom_auth: str, mapping: dict) -> tuple[str, str]:
    """Role+platform wins over platform, then manufacturer, then role.

    Access points return the module name ``skip`` so Prometheus drops them.
    They have no SNMP agent; Telegraf reads them through the controller.
    """
    default_auth = mapping.get("default_auth") or "ntt_snmpv3_auth"
    if custom_module:
        return custom_module, custom_auth or default_auth
    by_platform = mapping.get("by_platform") or {}
    by_mfr = mapping.get("by_manufacturer") or {}
    by_role = mapping.get("by_role") or {}
    by_role_platform = mapping.get("by_role_platform") or {}
    role_entry = by_role.get(role) if role else None
    if isinstance(role_entry, dict) and role_entry.get("skip_snmp"):
        return "skip", custom_auth or role_entry.get("auth") or default_auth
    chosen = None
    combo = "%s/%s" % (role, platform) if role and platform else ""
    if combo and combo in by_role_platform:
        chosen = by_role_platform[combo]
    elif platform and platform in by_platform:
        chosen = by_platform[platform]
    elif manufacturer and manufacturer in by_mfr:
        chosen = by_mfr[manufacturer]
    elif isinstance(role_entry, dict):
        chosen = role_entry
    if not chosen:
        modules = mapping.get("default_module") or "if_mib"
        auth = custom_auth or default_auth
        return modules if isinstance(modules, str) else ",".join(modules), auth
    return _join_modules(chosen, mapping, custom_auth)


def load_auth_map(path: str) -> dict:
    """IP to snmp-exporter auth name. The file has no secrets. Missing means the job default."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(ip): str(name) for ip, name in data.items() if ip and name}


def default_auth_map_path() -> str:
    return os.environ.get("IE_SNMP_AUTH_MAP", "/etc/ie/snmp/auth-by-ip.yml")


def target_for(device: dict, mapping: dict, auth_by_ip: dict | None = None) -> dict | None:
    """device is a plain dict (tests) or the fields the view extracts from a NetBox Device."""
    ip = (device.get("primary_ip4") or "").split("/")[0]
    if not ip:
        return None
    role = _slug(device.get("role"))
    manufacturer = _slug(device.get("manufacturer"))
    platform = _slug(device.get("platform"))
    module, auth = choose_module(role, manufacturer, platform, _slug(device.get("snmp_module")), _slug(device.get("snmp_auth")), mapping)
    resolved = (auth_by_ip or {}).get(ip)
    if resolved:
        auth = resolved
    labels = {
        "__meta_netbox_name": _slug(device.get("name")),
        "__meta_netbox_site_name": _slug(device.get("site")),
        "__meta_netbox_role": role,
        "__meta_netbox_device_type": _slug(device.get("device_type")),
        "__meta_netbox_region": _slug(device.get("region")),
        "__meta_netbox_primary_ip4": ip,
        "__meta_netbox_tenant": _slug(device.get("tenant")),
        "__meta_netbox_site_group": _slug(device.get("site_group")),
        "__meta_netbox_platform": platform,
        "__meta_netbox_manufacturer": manufacturer,
        "__meta_netbox_snmp_module": module,
        "__meta_netbox_snmp_auth": auth,
    }
    parent = _slug(device.get("parent"))
    if parent:
        labels["__meta_netbox_parent"] = parent
    if _slug(device.get("topology_parent")) == "yes":
        labels["__meta_netbox_topology_parent"] = "yes"
    return {"targets": [ip], "labels": labels}


def default_map_path() -> str:
    return os.environ.get("IE_MODULE_MAP", "/etc/ie/module-map.yml")


def _kind(tags) -> str:
    slugs = []
    for tag in tags or []:
        if isinstance(tag, dict):
            slugs.append(str(tag.get("slug") or tag.get("name") or "").lower())
        else:
            slugs.append(str(tag).lower())
    if "bank" in slugs:
        return "bank"
    if "third-party" in slugs:
        return "third-party"
    return ""


def service_target(service: dict) -> dict | None:
    """One blackbox target. Services without a third-party or bank tag are skipped.

    probe is the service custom field (icmp or tcp). Address is custom field
    target, otherwise the parent address the view already copied. TCP needs a port.
    """
    kind = _kind(service.get("tags"))
    if not kind:
        return None
    probe = str(service.get("probe") or "").strip().lower()
    if probe not in ("icmp", "tcp"):
        return None
    host = str(service.get("address") or "").strip()
    port = str(service.get("port") or "").strip()
    if not host:
        return None
    if probe == "tcp":
        if not port:
            return None
        target = "%s:%s" % (host, port)
    else:
        target = host.split("/")[0]
    labels = {
        "__meta_netbox_name": _slug(service.get("name")),
        "__meta_netbox_site_name": _slug(service.get("site")),
        "__meta_netbox_probe": probe,
        "__meta_netbox_kind": kind,
        "__meta_netbox_port": port,
    }
    return {"targets": [target], "labels": labels}


def service_targets(services: list, tag: str = "", probe: str = "") -> list[dict]:
    wanted_tag = (tag or "").strip().lower()
    wanted_probe = (probe or "").strip().lower()
    rows = []
    for service in services or []:
        if not isinstance(service, dict):
            continue
        item = service_target(service)
        if not item:
            continue
        if wanted_tag and item["labels"]["__meta_netbox_kind"] != wanted_tag:
            continue
        if wanted_probe and item["labels"]["__meta_netbox_probe"] != wanted_probe:
            continue
        rows.append(item)
    return rows


def vbs_target(site: dict) -> dict | None:
    """Blackbox ICMP to the site VBS server. No address means the site is not a target."""
    if not isinstance(site, dict):
        return None
    ip = str(site.get("vbs_server_ip") or "").strip()
    if not ip:
        return None
    host = ip.split("/")[0]
    name = _slug(site.get("name"))
    return {
        "targets": [host],
        "labels": {
            "__meta_netbox_name": name,
            "__meta_netbox_site_name": name,
            "__meta_netbox_probe": "icmp",
            "__meta_netbox_kind": "vbs",
            "__meta_netbox_port": _slug(site.get("vbs_server_port") or "9999"),
        },
    }


def vbs_targets(sites: list) -> list[dict]:
    rows = []
    for site in sites or []:
        item = vbs_target(site)
        if item:
            rows.append(item)
    return rows
