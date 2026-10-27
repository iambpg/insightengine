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


def choose_module(role: str, manufacturer: str, platform: str, custom_module: str, custom_auth: str, mapping: dict) -> tuple[str, str]:
    if custom_module:
        return custom_module, custom_auth or (mapping.get("default_auth") or "ntt_snmpv3_auth")
    by_platform = mapping.get("by_platform") or {}
    by_mfr = mapping.get("by_manufacturer") or {}
    by_role = mapping.get("by_role") or {}
    chosen = None
    if platform and platform in by_platform:
        chosen = by_platform[platform]
    elif manufacturer and manufacturer in by_mfr:
        chosen = by_mfr[manufacturer]
    elif role and role in by_role:
        chosen = by_role[role]
    if not chosen:
        modules = mapping.get("default_module") or "if_mib"
        auth = custom_auth or mapping.get("default_auth") or "ntt_snmpv3_auth"
        return modules if isinstance(modules, str) else ",".join(modules), auth
    modules = chosen.get("modules") or chosen.get("module") or "if_mib"
    if isinstance(modules, list):
        modules = ",".join(str(m) for m in modules)
    auth = custom_auth or chosen.get("auth") or mapping.get("default_auth") or "ntt_snmpv3_auth"
    return modules, auth


def target_for(device: dict, mapping: dict) -> dict | None:
    """device is a plain dict (tests) or the fields the view extracts from a NetBox Device."""
    ip = (device.get("primary_ip4") or "").split("/")[0]
    if not ip:
        return None
    role = _slug(device.get("role"))
    manufacturer = _slug(device.get("manufacturer"))
    platform = _slug(device.get("platform"))
    module, auth = choose_module(role, manufacturer, platform, _slug(device.get("snmp_module")), _slug(device.get("snmp_auth")), mapping)
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
    return {"targets": [ip], "labels": labels}


def default_map_path() -> str:
    return os.environ.get("IE_MODULE_MAP", "/etc/ie/module-map.yml")
