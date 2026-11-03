"""Vendor-neutral device health for the UI.

SNMP modules and Telegraf stay vendor-specific. This module turns those
samples into the five groups every device type is asked for: interfaces,
memory, fans, power supplies and temperature. A group the platform does
not implement is explicit ("not supported by this device"), never blank.
"""

from __future__ import annotations

NOT_SUPPORTED = "not supported by this device"

# temperature: "value" means degrees C, "status" means a state word is the
# best the platform usually offers (Catalyst 2960 ENVMON).
PROFILES = {
    "ios": {
        "label": "Cisco Catalyst IOS",
        "interfaces": True,
        "memory": True,
        "fan": True,
        "psu": True,
        "temperature": "status",
    },
    "iosxe": {
        "label": "Cisco IOS-XE",
        "interfaces": True,
        "memory": True,
        "fan": True,
        "psu": True,
        "temperature": "value",
    },
    "nxos": {
        "label": "Cisco NX-OS",
        "interfaces": True,
        "memory": True,
        "fan": True,
        "psu": True,
        "temperature": "value",
    },
    "asa": {
        "label": "Cisco ASA",
        "interfaces": True,
        "memory": True,
        "fan": True,
        "psu": True,
        "temperature": "status",
    },
    "aireos": {
        "label": "Cisco AireOS WLC",
        "interfaces": True,
        "memory": True,
        "fan": False,
        "psu": True,
        "temperature": False,
        "wlc": True,
    },
    "iosxe-wlc": {
        "label": "Cisco Catalyst 9800",
        "interfaces": True,
        "memory": True,
        "fan": True,
        "psu": True,
        "temperature": "value",
        "wlc": True,
    },
    "fortigate": {
        "label": "Fortinet FortiGate",
        "interfaces": True,
        "memory": True,
        "fan": True,
        "psu": True,
        "temperature": "value",
    },
    "paloalto": {
        "label": "Palo Alto PAN-OS",
        "interfaces": True,
        "memory": True,
        "fan": True,
        "psu": True,
        "temperature": "value",
    },
    "ap": {
        "label": "Cisco access point",
        "interfaces": False,
        "memory": False,
        "fan": False,
        "psu": False,
        "temperature": False,
        "access_point": True,
    },
    "generic": {
        "label": "Other",
        "interfaces": True,
        "memory": False,
        "fan": False,
        "psu": False,
        "temperature": False,
    },
}


def _blob(*parts: str) -> str:
    return " ".join(str(part or "") for part in parts).lower()


def classify_profile(role: str = "", platform: str = "", manufacturer: str = "", model: str = "") -> str:
    """Pick the health profile from NetBox role, platform, manufacturer and model."""
    role_l = (role or "").strip().lower().replace("_", "-")
    text = _blob(role, platform, manufacturer, model)
    if role_l in ("ap", "access-point", "wireless-ap", "access-ap") or any(
        token in text for token in ("ceiling-ap", "air-ap", "air-cap", "access point", "wireless ap")
    ):
        return "ap"
    if any(token in text for token in ("fortigate", "fortios", "fortinet")):
        return "fortigate"
    if any(token in text for token in ("palo", "pan-os", "panos")) or " pa-" in " " + text:
        return "paloalto"
    wlc = role_l in ("wireless-controller", "wlc") or any(
        token in text for token in ("wireless controller", "aireos", "air-ct", "catalyst 9800", "c9800")
    )
    iosxe = any(token in text for token in ("ios-xe", "iosxe", "cat9", "c9300", "c9500", "c9800", "isr", "sd-wan"))
    if wlc and (iosxe or "9800" in text or "c9800" in text):
        return "iosxe-wlc"
    if wlc or "aireos" in text or "air-ct" in text:
        return "aireos"
    if any(token in text for token in ("nx-os", "nxos", "nexus")):
        return "nxos"
    if "asa" in text.split() or "adaptive security" in text:
        return "asa"
    if iosxe:
        return "iosxe"
    if any(token in text for token in ("2960", "catalyst", "ios", "cisco")):
        return "ios"
    return "generic"


def _unsupported(group_id: str, label: str, detail: str = NOT_SUPPORTED) -> dict:
    return {
        "id": group_id,
        "label": label,
        "supported": False,
        "status": "unsupported",
        "value": NOT_SUPPORTED,
        "detail": detail,
    }


def _known(group_id: str, label: str, status: str, value: str, detail: str) -> dict:
    return {
        "id": group_id,
        "label": label,
        "supported": True,
        "status": status,
        "value": value,
        "detail": detail,
    }


def _missing(group_id: str, label: str, detail: str) -> dict:
    return _known(group_id, label, "unknown", "No sample", detail)


def _ratio_status(ratio: float | None) -> str:
    if ratio is None:
        return "unknown"
    if ratio >= 0.95:
        return "fail"
    if ratio >= 0.90:
        return "warn"
    return "ok"


def _temp_status(celsius: float | None, state: str) -> str:
    word = (state or "").lower()
    if word in ("critical", "shutdown", "nonoperational", "notfunctioning"):
        return "fail"
    if word in ("warning", "warn"):
        return "warn"
    if celsius is None:
        return "ok" if word in ("normal", "ok", "up") else "unknown"
    if celsius >= 75:
        return "fail"
    if celsius >= 60:
        return "warn"
    return "ok"


def _state_status(states: list[str]) -> str:
    bad = {"critical", "shutdown", "notfunctioning", "down", "failed", "false"}
    warn = {"warning", "warn"}
    words = [item.lower() for item in states if item]
    if any(item in bad for item in words):
        return "fail"
    if any(item in warn for item in words):
        return "warn"
    if words:
        return "ok"
    return "unknown"


def interface_rows(ports: list[dict], critical_names: set[str], limit: int = 8) -> list[dict]:
    """Top interfaces by utilisation. critical_names are lower-case NetBox names."""
    ranked = sorted(ports or [], key=lambda port: float(port.get("utilisation") or 0), reverse=True)
    rows = []
    for port in ranked[:limit]:
        name = str(port.get("name") or "")
        blob = name.lower()
        alias = str(port.get("alias") or port.get("description") or "").lower()
        marked = blob in critical_names or "critical-path" in blob or "critical-path" in alias or "uplink" in blob or "uplink" in alias
        drops = port.get("dropsRate")
        rows.append({
            "name": name or str(port.get("id") or ""),
            "ifIndex": str(port.get("id") or ""),
            "utilization": None if port.get("utilisation") is None else round(float(port.get("utilisation") or 0) / 100.0, 4),
            "dropsRate": None if drops is None else round(float(drops), 4),
            "errorsRate": None if port.get("errors") is None else round(float(port.get("errors") or 0) / 60.0, 4),
            "criticalPath": bool(marked),
        })
    return rows


def build_health_panel(
    profile_id: str,
    *,
    memory_ratio: float | None = None,
    memory_detail: str = "",
    fan_states: list[str] | None = None,
    psu_states: list[str] | None = None,
    temp_c: float | None = None,
    temp_state: str = "",
    ports: list[dict] | None = None,
    critical_names: set[str] | None = None,
    wlc_joined: float | None = None,
    wlc_clients: float | None = None,
    ap: dict | None = None,
) -> dict:
    profile = PROFILES.get(profile_id) or PROFILES["generic"]
    groups = []

    if profile["memory"]:
        if memory_ratio is None:
            groups.append(_missing("memory", "Memory", memory_detail or "No memory sample yet"))
        else:
            groups.append(_known(
                "memory", "Memory", _ratio_status(memory_ratio),
                "%.0f%%" % (memory_ratio * 100),
                memory_detail or "Used ratio",
            ))
    else:
        groups.append(_unsupported("memory", "Memory"))

    if profile["fan"]:
        states = [item for item in (fan_states or []) if item and item.lower() != "notpresent"]
        if not states:
            groups.append(_missing("fan", "Fans", "No fan sample yet"))
        else:
            status = _state_status(states)
            bad = [item for item in states if _state_status([item]) != "ok"]
            groups.append(_known(
                "fan", "Fans", status,
                "All normal" if status == "ok" else "%d degraded" % len(bad),
                "States: %s" % ", ".join(states),
            ))
    else:
        detail = NOT_SUPPORTED
        if profile_id == "aireos":
            detail = "AireOS exposes fan failure as a trap, not a polled table. " + NOT_SUPPORTED
        groups.append(_unsupported("fan", "Fans", detail))

    if profile["psu"]:
        states = [item for item in (psu_states or []) if item and item.lower() not in ("notpresent", "false")]
        # A present-but-not-operational supply is a failure. Keep "false" operational flags.
        raw = list(psu_states or [])
        if not raw:
            groups.append(_missing("psu", "Power supplies", "No power-supply sample yet"))
        else:
            status = _state_status(raw)
            groups.append(_known(
                "psu", "Power supplies", status,
                "%d reported" % len(raw),
                "States: %s" % ", ".join(raw),
            ))
    else:
        groups.append(_unsupported("psu", "Power supplies"))

    temp_mode = profile["temperature"]
    if not temp_mode:
        detail = NOT_SUPPORTED
        if profile_id == "aireos":
            detail = "AireOS has no polled temperature table. " + NOT_SUPPORTED
        groups.append(_unsupported("temperature", "Temperature", detail))
    elif temp_c is None and not temp_state:
        groups.append(_missing(
            "temperature", "Temperature",
            "No temperature sample yet" if temp_mode == "value" else "No temperature status yet",
        ))
    elif temp_c is None:
        groups.append(_known(
            "temperature", "Temperature", _temp_status(None, temp_state),
            temp_state, "Status only. This platform often has no degree reading.",
        ))
    else:
        groups.append(_known(
            "temperature", "Temperature", _temp_status(temp_c, temp_state),
            "%.0f°C" % temp_c,
            temp_state or "Highest sensor",
        ))

    interfaces_supported = bool(profile["interfaces"])
    rows = interface_rows(ports or [], critical_names or set()) if interfaces_supported else []
    panel = {
        "profile": profile_id,
        "profileLabel": profile["label"],
        "groups": groups,
        "interfacesSupported": interfaces_supported,
        "interfaces": rows,
        "interfacesNote": "" if interfaces_supported else NOT_SUPPORTED,
        "wlc": None,
        "accessPoint": None,
    }
    if profile.get("wlc"):
        panel["wlc"] = {
            "joinedAps": None if wlc_joined is None else int(wlc_joined),
            "clients": None if wlc_clients is None else int(wlc_clients),
            "note": (
                "Controller system stats come from snmp-exporter. "
                "Per-AP status, radios, channel utilization, clients and uptime come from Telegraf."
            ),
        }
    if profile.get("access_point"):
        panel["accessPoint"] = {
            "note": (
                "This AP has no SNMP agent. Status, radios, channel utilization, "
                "clients and uptime are collected by Telegraf from its wireless controller."
            ),
            "status": (ap or {}).get("status") or NOT_SUPPORTED,
            "clients": (ap or {}).get("clients"),
            "uptimeSeconds": (ap or {}).get("uptimeSeconds"),
            "radios": list((ap or {}).get("radios") or []),
        }
        panel["interfacesNote"] = (
            "Interface counters are not on the AP. Radio channel utilization is on the controller via Telegraf."
        )
    return panel


def aireos_psu_states(samples: list[dict]) -> list[str]:
    """Only supplies the controller says are present. A missing second PSU is normal."""
    by_name = {}
    for sample in samples or []:
        metric = sample.get("metric") or {}
        name = str(metric.get("__name__") or "")
        if name.endswith("_info"):
            continue
        try:
            by_name[name] = int(float((sample.get("value") or [None, None])[1]))
        except (TypeError, ValueError, IndexError):
            continue
    states = []
    for index in (1, 2):
        present = by_name.get("agentSwitchInfoPowerSupply%dPresent" % index)
        operational = by_name.get("agentSwitchInfoPowerSupply%dOperational" % index)
        if present != 1:
            continue
        states.append("normal" if operational == 1 else "failed")
    return states


def critical_names_from_interfaces(interfaces: list[dict]) -> set[str]:
    names = set()
    for row in interfaces or []:
        if not isinstance(row, dict):
            continue
        if row.get("criticalPath"):
            name = str(row.get("name") or "").strip().lower()
            if name:
                names.add(name)
    return names


def mark_critical_interface(raw: dict) -> bool:
    """NetBox tag critical-path, or a name/description that says uplink or critical-path."""
    tags = raw.get("tags") or []
    bits = []
    for tag in tags:
        if isinstance(tag, dict):
            bits.append(str(tag.get("slug") or ""))
            bits.append(str(tag.get("name") or ""))
        else:
            bits.append(str(tag))
    bits.append(str(raw.get("name") or ""))
    bits.append(str(raw.get("description") or ""))
    text = " ".join(bits).lower()
    return "critical-path" in text or "uplink" in text


def page_rows(rows: list[dict], *, page: int, page_size: int, q: str = "", wlc: str = "", site: str = "", status: str = "") -> dict:
    """Filter then slice. Callers pass the cached AP snapshot, never 8500 rows to the browser."""
    page = max(1, int(page or 1))
    page_size = min(100, max(1, int(page_size or 50)))
    needle = (q or "").strip().lower()
    want_wlc = (wlc or "").strip().lower()
    want_site = (site or "").strip().lower()
    want_status = (status or "").strip().lower()
    matched = []
    for row in rows:
        if want_wlc and want_wlc not in str(row.get("wlc") or "").lower():
            continue
        if want_site and want_site not in str(row.get("site") or "").lower():
            continue
        if want_status and want_status != str(row.get("status") or "").lower():
            continue
        if needle:
            blob = " ".join([
                str(row.get("name") or ""),
                str(row.get("mac") or ""),
                str(row.get("wlc") or ""),
                str(row.get("site") or ""),
            ]).lower()
            if needle not in blob:
                continue
        matched.append(row)
    total = len(matched)
    start = (page - 1) * page_size
    return {
        "rows": matched[start:start + page_size],
        "total": total,
        "page": page,
        "pageSize": page_size,
    }
