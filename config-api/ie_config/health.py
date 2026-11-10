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
    # 2960, 3560, Catalyst 1000 and the SG small-business switches have a CPU
    # and RAM. They do not report fans, power supplies or temperature.
    "ios-basic": {
        "label": "Cisco switch",
        "interfaces": True,
        "cpu": True,
        "memory": True,
        "fan": False,
        "psu": False,
        "temperature": False,
        "hide_unsupported": True,
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
        "cpu": False,
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
    if any(token in text for token in ("2960", "3560", "c1000", "catalyst 1000", "sg350", "sg500")):
        return "ios-basic"
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
            "errorsRate": None if port.get("errors") is None else round(float(port.get("errors") or 0) / 300.0, 4),
            "criticalPath": bool(marked),
        })
    return rows


def build_health_panel(
    profile_id: str,
    *,
    cpu: float | None = None,
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

    if profile.get("cpu", True):
        if cpu is None:
            groups.append(_missing("cpu", "CPU", "No CPU sample yet"))
        else:
            cpu_status = "fail" if cpu >= 95 else "warn" if cpu >= 80 else "ok"
            groups.append(_known("cpu", "CPU", cpu_status, "%.0f%%" % cpu, "5 minute average"))

    if profile["memory"]:
        if memory_ratio is None:
            groups.append(_missing("memory", "Memory", memory_detail or "No memory sample yet"))
        else:
            groups.append(_known(
                "memory", "Memory", _ratio_status(memory_ratio),
                "%.0f%%" % (memory_ratio * 100),
                memory_detail or "Used ratio",
            ))
    elif not profile.get("hide_unsupported"):
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
        if not profile.get("hide_unsupported"):
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
        if not profile.get("hide_unsupported"):
            groups.append(_unsupported("psu", "Power supplies"))

    temp_mode = profile["temperature"]
    if not temp_mode:
        detail = NOT_SUPPORTED
        if profile_id == "aireos":
            detail = "AireOS has no polled temperature table. " + NOT_SUPPORTED
        if not profile.get("hide_unsupported"):
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


STALE_SECONDS = 30 * 60
CPU_WARN = 80.0
CPU_CRITICAL = 95.0
MEMORY_WARN = 0.90
MEMORY_CRITICAL = 0.95
TEMP_WARN = 60.0
TEMP_CRITICAL = 75.0
# Port error counts are the increase over 5 minutes. A warning stays on the
# port and does not move the device badge. Fifty or more is critical and does.
ERRORS_WARN_5M = 20.0
ERRORS_CRITICAL_5M = 50.0
CRIT_PATH_UTIL = 80.0
RADIO_UTIL = 0.75

_EFFECT_RANK = {"healthy": 0, "warning": 1, "critical": 2, "unreachable": 3}
_BAD_STATE = {"critical", "shutdown", "notfunctioning", "down", "failed", "false"}
_WARN_STATE = {"warning", "warn"}


def _num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ago(seconds) -> str:
    value = _num(seconds)
    if value is None:
        return "—"
    whole = max(0, int(value))
    if whole < 60:
        return "%ds ago" % whole
    minutes, sec = divmod(whole, 60)
    if minutes < 60:
        return "%dm %ds ago" % (minutes, sec) if sec else "%dm ago" % minutes
    hours, minutes = divmod(minutes, 60)
    if hours < 48:
        return "%dh %dm ago" % (hours, minutes)
    days, hours = divmod(hours, 24)
    return "%dd %dh ago" % (days, hours)


def _effect_for(severity: str) -> str:
    if severity == "critical":
        return "critical"
    if severity == "warning":
        return "warning"
    return "healthy"


def _cause(item_id: str, severity: str, title: str, detail: str, value: str, threshold: str, source: str, since: str, target: str, effect: str | None = None) -> dict:
    return {
        "id": item_id,
        "severity": severity,
        "title": title,
        "detail": detail,
        "value": value,
        "threshold": threshold,
        "source": source,
        "since": since or "—",
        "target": target or "device",
        "effect": effect or _effect_for(severity),
    }


def _health_from_items(items: list[dict]) -> str:
    best = "healthy"
    for item in items:
        effect = str(item.get("effect") or "healthy")
        if _EFFECT_RANK.get(effect, 0) > _EFFECT_RANK.get(best, 0):
            best = effect
    return best


def _state_word(state: str) -> str:
    return (state or "").strip().lower().replace(" ", "").replace("_", "")


def _reachability(snapshot: dict, since: str) -> list[dict]:
    probe = snapshot.get("probe")
    snmp = snapshot.get("snmpUp")
    age = snapshot.get("lastAgeS")
    ports_total = snapshot.get("portsTotal")
    items = []
    if probe == 0:
        items.append(_cause(
            "probe", "critical", "Probe failed",
            "The ICMP probe is not succeeding.",
            "0", "1 (success)", "prometheus", since, "probe", "unreachable",
        ))
    if _num(age) is not None and float(age) > STALE_SECONDS:
        items.append(_cause(
            "stale", "critical", "Telemetry is stale",
            "No fresh SNMP or probe sample within 30 minutes.",
            _ago(age), "30m", "prometheus", since, "poll", "unreachable",
        ))
    if probe is None and snmp is None and "probe" in snapshot and "snmpUp" in snapshot:
        items.append(_cause(
            "no-sample", "critical", "No probe or SNMP sample",
            "Prometheus has neither an ICMP probe nor an SNMP scrape for this device.",
            "none", "a recent sample", "prometheus", since, "device", "unreachable",
        ))
    if snmp == 0 and probe != 1 and probe != 0:
        items.append(_cause(
            "snmp-down", "critical", "SNMP scrape is down",
            "The SNMP exporter reports this device down and ICMP is not succeeding.",
            "0", "1 (up)", "prometheus", since, "snmp", "unreachable",
        ))
    if snmp == 0 and probe == 1:
        items.append(_cause(
            "snmp-warn", "warning", "SNMP scrape is down",
            "ICMP answers, but the SNMP scrape is down.",
            "0", "1 (up)", "prometheus", since, "snmp",
        ))
    if probe == 1 and snmp is None and not ports_total:
        items.append(_cause(
            "no-interfaces", "warning", "No interface table",
            "ICMP answers and no SNMP interface table has been collected.",
            "0 interfaces", "an interface table", "prometheus", since, "interfaces",
        ))
    return items


def _critical_port(port: dict) -> bool:
    if port.get("criticalPath"):
        return True
    blob = " ".join(str(port.get(key) or "") for key in ("name", "alias", "description")).lower()
    return "critical-path" in blob or "uplink" in blob


def _interface_items(snapshot: dict, since: str) -> list[dict]:
    ports = snapshot.get("ports")
    if isinstance(ports, list) and ports:
        items = []
        for port in ports:
            if not isinstance(port, dict):
                continue
            name = str(port.get("name") or port.get("id") or "interface")
            errors = _num(port.get("errors"))
            if errors is not None and errors >= ERRORS_CRITICAL_5M:
                items.append(_cause(
                    "if-err-%s" % name, "critical", "Interface input errors",
                    "%s has at least 50 input errors in 5 minutes." % name,
                    "%.0f/5m" % errors, "50/5m", "prometheus", since, name,
                ))
            elif errors is not None and errors >= ERRORS_WARN_5M:
                # Listed on the port as a warning. effect stays healthy so the
                # device badge does not move.
                items.append(_cause(
                    "if-err-%s" % name, "warning", "Interface input errors",
                    "%s has at least 20 input errors in 5 minutes." % name,
                    "%.0f/5m" % errors, "20/5m", "prometheus", since, name,
                    effect="healthy",
                ))
            util = _num(port.get("utilisation"))
            if util is None:
                util = _num(port.get("utilization"))
                if util is not None and util <= 1:
                    util = util * 100.0
            if _critical_port(port) and util is not None and util >= CRIT_PATH_UTIL:
                items.append(_cause(
                    "if-util-%s" % name, "warning", "Critical-path utilization high",
                    "%s utilization is above 80%%." % name,
                    "%.0f%%" % util, "80%", "prometheus", since, name,
                ))
            drops = _num(port.get("dropsRate"))
            if _critical_port(port) and drops is not None and drops > 0:
                items.append(_cause(
                    "if-drops-%s" % name, "warning", "Critical-path drops",
                    "%s is dropping frames." % name,
                    "%.2f/s" % drops, "0/s", "prometheus", since, name,
                ))
        return items
    items = []
    fault = int(_num(snapshot.get("portsFault")) or 0) if "portsFault" in snapshot else 0
    warn = int(_num(snapshot.get("portsWarn")) or 0) if "portsWarn" in snapshot else 0
    if fault > 0:
        items.append(_cause(
            "ports-fault", "critical", "Interface input errors",
            "%d interface%s with at least 50 input errors in 5 minutes." % (fault, "" if fault == 1 else "s"),
            str(fault), "0", "prometheus", since, "interfaces",
        ))
    if warn > 0:
        items.append(_cause(
            "ports-warn", "warning", "Interface input errors",
            "%d interface%s with at least 20 input errors in 5 minutes." % (warn, "" if warn == 1 else "s"),
            str(warn), "0", "prometheus", since, "interfaces",
            effect="healthy",
        ))
    return items


def _threshold_items(snapshot: dict, since: str) -> list[dict]:
    items = []
    cpu = _num(snapshot.get("cpu"))
    if cpu is not None and cpu >= CPU_WARN:
        severity = "critical" if cpu >= CPU_CRITICAL else "warning"
        items.append(_cause(
            "cpu", severity, "CPU high",
            "CPU is above the %s threshold." % ("95%" if severity == "critical" else "80%"),
            "%.0f%%" % cpu, "95%" if severity == "critical" else "80%", "prometheus", since, "cpu",
        ))
    ratio = _num(snapshot.get("memoryRatio"))
    if ratio is None and _num(snapshot.get("memoryPercent")) is not None:
        ratio = float(snapshot["memoryPercent"]) / 100.0
    if ratio is not None and ratio >= MEMORY_WARN:
        severity = "critical" if ratio >= MEMORY_CRITICAL else "warning"
        items.append(_cause(
            "memory", severity, "Memory high",
            "Memory used ratio is above the threshold.",
            "%.0f%%" % (ratio * 100), "95%" if severity == "critical" else "90%", "prometheus", since, "memory",
        ))
    temp = _num(snapshot.get("tempC"))
    if temp is not None and temp >= TEMP_WARN:
        severity = "critical" if temp >= TEMP_CRITICAL else "warning"
        items.append(_cause(
            "temperature", severity, "Temperature high",
            "A temperature sensor is above the threshold.",
            "%.0f°C" % temp, "75°C" if severity == "critical" else "60°C", "prometheus", since, "temperature",
        ))
    temp_state = _state_word(str(snapshot.get("tempState") or ""))
    if temp is None and temp_state in _BAD_STATE | _WARN_STATE:
        severity = "critical" if temp_state in _BAD_STATE else "warning"
        items.append(_cause(
            "temperature-state", severity, "Temperature status",
            "The platform reported a temperature state and no degree reading.",
            temp_state, "normal", "prometheus", since, "temperature",
        ))
    for index, state in enumerate(snapshot.get("fans") or []):
        word = _state_word(str(state))
        if not word or word in ("notpresent", "normal", "ok", "up"):
            continue
        if word not in _BAD_STATE | _WARN_STATE:
            continue
        severity = "critical" if word in _BAD_STATE else "warning"
        items.append(_cause(
            "fan-%d" % index, severity, "Fan degraded",
            "Fan %d state is %s." % (index + 1, state),
            str(state), "normal", "prometheus", since, "fan %d" % (index + 1),
        ))
    for index, state in enumerate(snapshot.get("psus") or []):
        word = _state_word(str(state))
        if not word or word in ("notpresent", "normal", "ok", "up"):
            continue
        if word not in _BAD_STATE | _WARN_STATE:
            continue
        severity = "critical" if word in _BAD_STATE else "warning"
        items.append(_cause(
            "psu-%d" % index, severity, "Power supply degraded",
            "Power supply %d state is %s." % (index + 1, state),
            str(state), "normal", "prometheus", since, "psu %d" % (index + 1),
        ))
    if snapshot.get("fanOk") == 0:
        items.append(_cause(
            "fan-ok", "critical", "Fan failed",
            "A normalized fan series is failed.",
            "0", "1 (ok)", "prometheus", since, "fan",
        ))
    if snapshot.get("psuOk") == 0:
        items.append(_cause(
            "psu-ok", "critical", "Power supply failed",
            "A normalized power-supply series is failed.",
            "0", "1 (ok)", "prometheus", since, "psu",
        ))
    return items


def _ap_items(snapshot: dict, since: str) -> list[dict]:
    items = []
    status = str(snapshot.get("apStatus") or "").strip().lower()
    if status == "down":
        items.append(_cause(
            "ap-down", "critical", "Access point down",
            "The wireless controller reports this access point down.",
            "down", "up", "telegraf", since, str(snapshot.get("apName") or "access point"),
        ))
    down = _num(snapshot.get("apDown"))
    if down is not None and down > 0:
        count = int(down)
        items.append(_cause(
            "aps-down", "warning", "Access points down",
            "%d joined access point%s down." % (count, "" if count == 1 else "s"),
            str(count), "0", "telegraf", since, "access points",
        ))
    for radio in snapshot.get("radios") or []:
        if not isinstance(radio, dict):
            continue
        util = _num(radio.get("utilization"))
        if util is None or util < RADIO_UTIL:
            continue
        slot = str(radio.get("slot") or "")
        items.append(_cause(
            "radio-%s" % (slot or "util"), "warning", "Radio channel utilization high",
            "Radio %s channel utilization is above 75%%." % (slot or ""),
            "%.0f%%" % (util * 100), "75%", "telegraf", since, "radio %s" % (slot or ""),
        ))
    return items


def _alert_items(snapshot: dict) -> list[dict]:
    items = []
    for alert in snapshot.get("alerts") or []:
        if not isinstance(alert, dict):
            continue
        if alert.get("status") not in (None, "", "open"):
            continue
        severity = str(alert.get("severity") or "warning")
        if severity not in ("critical", "warning", "info"):
            severity = "warning"
        age = alert.get("ageSeconds")
        since = str(alert.get("since") or "") or (_ago(age) if age is not None else "—")
        item_id = str(alert.get("id") or alert.get("title") or "alert")
        items.append(_cause(
            "alert-%s" % item_id, severity,
            str(alert.get("title") or "Alert"),
            str(alert.get("detail") or ""),
            severity, "clear", "alertmanager", since,
            str(alert.get("target") or alert.get("deviceHostname") or "device"),
        ))
    return items


def explain_health(snapshot: dict | None = None) -> dict:
    """One health badge and the items that produce it.

    List rows and the device page both call this. The badge is the worst
    item, so the page lists exactly the causes of the badge it shows.
    An empty item list is healthy. Info items are listed and do not move
    the badge. Reachability failures stay unreachable, which outranks
    critical. Callers omit probe and SNMP keys for an access point that
    has no SNMP agent of its own.
    """
    snap = snapshot or {}
    since = str(snap.get("since") or "—")
    items = []
    if any(key in snap for key in ("probe", "snmpUp", "lastAgeS")):
        items.extend(_reachability(snap, since))
    items.extend(_interface_items(snap, since))
    items.extend(_threshold_items(snap, since))
    items.extend(_ap_items(snap, since))
    items.extend(_alert_items(snap))
    health = _health_from_items(items)
    return {"health": health, "items": items}


def classify_health(probe, snmp_up, last_age_s, ports_fault, ports_warn, ports_total) -> str:
    """Badge from the same items the device page lists for these signals."""
    return explain_health({
        "probe": probe,
        "snmpUp": snmp_up,
        "lastAgeS": last_age_s,
        "portsFault": ports_fault or 0,
        "portsWarn": ports_warn or 0,
        "portsTotal": ports_total or 0,
    })["health"]


def match_access_point(devices: list[dict], ap: dict) -> dict | None:
    """NetBox device for an access point. Serial wins, then the AP name."""
    serial = str((ap or {}).get("serial") or "").strip().lower()
    name = str((ap or {}).get("name") or "").strip().lower()
    if serial and serial not in ("—", "-", "unknown"):
        for device in devices or []:
            got = str(device.get("serial") or "").strip().lower()
            nested = device.get("_device") if isinstance(device.get("_device"), dict) else {}
            if not got:
                got = str((nested or {}).get("serial") or "").strip().lower()
            if got and got == serial:
                return device
    if name:
        for device in devices or []:
            got = str(device.get("name") or device.get("hostname") or "").strip().lower()
            if got and got == name:
                return device
    return None


def suggest_ap_site(ap: dict, sites: list[dict] | None = None) -> str:
    """Prefer a NetBox site whose name or slug matches the site tag, then the location."""
    catalog = []
    for site in sites or []:
        if not isinstance(site, dict):
            continue
        catalog.append((str(site.get("name") or "").strip(), str(site.get("slug") or "").strip().lower()))
    for raw in (ap.get("siteTag"), ap.get("location"), ap.get("netboxSite"), ap.get("site")):
        text = str(raw or "").strip()
        if not text:
            continue
        low = text.lower()
        for name, slug in catalog:
            if not name:
                continue
            if low == name.lower() or (slug and low == slug):
                return name
        for name, slug in catalog:
            if name and (low in name.lower() or name.lower() in low or (slug and slug in low)):
                return name
        if not catalog:
            return text
    for raw in (ap.get("netboxSite"), ap.get("site")):
        text = str(raw or "").strip()
        if text:
            return text
    return ""


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
                str(row.get("netboxSite") or ""),
                str(row.get("model") or ""),
                str(row.get("neighborSwitch") or ""),
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
