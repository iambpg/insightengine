"""Manager-readable account of one site over a chosen window.

Numbers come from the caller. This module does not query Prometheus or Loki
and does not invent a reading that was not supplied.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

_VIRTUAL = re.compile(
    r"(?i)^(vlan|vl\d|loopback|lo\d*|null\d*|tunnel|tu\d|bdi|nve|port-channel|po\d|cpu|stackport|internal(?!\d))"
)
_LINK_DOWN = re.compile(r"(?i)(changed state to down|link[- ]?down|UPDOWN:.*\bdown\b)")
_LINK_UP = re.compile(r"(?i)(changed state to up|link[- ]?up|UPDOWN:.*\bup\b)")
_CONFIG = re.compile(
    r"(?i)(CONFIG_I|SYS-5-CONFIG|configured from|configuration (was )?chang|config chang|startup-config|commit performed)"
)
_SECRET = re.compile(r"(?i)(community|password|passphrase|\bsecret\b)")
_BAD_SEVERITY = {"error", "critical", "alert", "emergency"}
_NOTICE_CAP = 40


def lane_of(role: str, form: str) -> str:
    blob = "%s %s" % (role or "", form or "")
    blob = blob.lower()
    if re.search(r"access point|ceiling-ap|wireless", blob):
        return "wifi"
    if re.search(r"firewall|sd-?wan|router", blob):
        return "wan"
    if re.search(r"switch|chassis", blob):
        return "lan"
    return "other"


def name_regex(names: list[str]) -> str:
    parts = []
    for name in names:
        text = str(name or "").strip()
        if not text:
            continue
        parts.append(re.sub(r"([.^$*+?()\[\]{}|\\])", r"\\\1", text))
    return "|".join(parts[:60])


def prom_duration(window_s: int) -> str:
    window_s = max(60, int(window_s))
    if window_s % 86400 == 0:
        return "%dd" % (window_s // 86400)
    if window_s % 3600 == 0:
        return "%dh" % (window_s // 3600)
    return "%dm" % (window_s // 60)


def bytes_to_mbps(value, window_s: int):
    if value is None:
        return None
    return float(value) * 8.0 / max(60, int(window_s)) / 1_000_000.0


def window_label(range_key: str, custom_min: int) -> str:
    if range_key == "1h":
        return "the past hour"
    if range_key == "6h":
        return "the past 6 hours"
    if range_key == "24h":
        return "the past 24 hours"
    if range_key == "7d":
        return "the past 7 days"
    hours = max(1, int(custom_min or 60) // 60)
    if hours == 1:
        return "the past hour"
    return "the past %d hours" % hours


def host_values(samples) -> list[tuple[str, float]]:
    found = []
    for sample in samples or []:
        if not isinstance(sample, dict):
            continue
        metric = sample.get("metric") or {}
        host = str(metric.get("hostname") or metric.get("ap_name") or metric.get("ap") or "").strip()
        value = _value(sample)
        if host and value is not None:
            found.append((host, value))
    return found


def scalar(samples):
    for sample in samples or []:
        value = _value(sample)
        if value is not None:
            return value
    return None


def talkers_from(inbound, outbound, window_s: int) -> list[dict]:
    window_s = max(60, int(window_s))
    totals: dict[tuple[str, str], dict] = {}

    def add(samples, key: str):
        for sample in samples or []:
            if not isinstance(sample, dict):
                continue
            metric = sample.get("metric") or {}
            host = str(metric.get("hostname") or "").strip()
            port = str(metric.get("ifName") or metric.get("ifDescr") or "").strip()
            if not host or not port or _VIRTUAL.match(port):
                continue
            value = _value(sample)
            if value is None:
                continue
            row = totals.setdefault((host, port), {"device": host, "port": port, "inMbps": 0.0, "outMbps": 0.0})
            row[key] += value * 8.0 / window_s / 1_000_000.0

    add(inbound, "inMbps")
    add(outbound, "outMbps")
    ranked = [row for row in totals.values() if row["inMbps"] + row["outMbps"] > 0]
    ranked.sort(key=lambda row: row["inMbps"] + row["outMbps"], reverse=True)
    cleaned = []
    for row in ranked[:8]:
        cleaned.append({
            "device": row["device"],
            "port": row["port"],
            "inMbps": round(row["inMbps"], 3),
            "outMbps": round(row["outMbps"], 3),
        })
    return cleaned


def classify_logs(lines: list[dict]) -> dict:
    link_down = []
    link_up = []
    config_rows = []
    problems = []
    kept = 0
    for line in lines or []:
        if not isinstance(line, dict):
            continue
        message = str(line.get("message") or "").strip()
        if not message or _SECRET.search(message):
            continue
        kept += 1
        item = _log_item(line, message)
        if _CONFIG.search(message):
            config_rows.append(item)
            continue
        if _LINK_DOWN.search(message):
            link_down.append(item)
            continue
        if _LINK_UP.search(message):
            link_up.append(item)
            continue
        if str(line.get("severity") or "").lower() in _BAD_SEVERITY:
            problems.append(item)
    return {
        "lines": kept,
        "linkDown": len(link_down),
        "linkUp": len(link_up),
        "configChanges": len(config_rows),
        "examples": config_rows[:3],
        "problems": len(problems),
        "linkDownItems": link_down[:_NOTICE_CAP],
        "linkUpItems": link_up[:_NOTICE_CAP],
        "configItems": config_rows[:_NOTICE_CAP],
        "problemItems": problems[:_NOTICE_CAP],
    }


def build_briefing(
    *,
    window_label: str,
    devices: list[dict],
    logs: list[dict],
    cpu,
    memory,
    port_errors,
    ports_down,
    clients,
    noise,
    interference,
    wan_in,
    wan_out,
    wan_known: bool,
    loss,
    talkers: list[dict],
    sla: dict | None = None,
) -> dict:
    grouped = {"lan": [], "wifi": [], "wan": [], "other": []}
    for device in devices or []:
        grouped[lane_of(device.get("role") or "", device.get("formFactor") or "")].append(device)
    history = classify_logs(logs)
    sections = [
        {"id": "lan", "title": "LAN Network", "text": _lan_text(window_label, grouped["lan"], ports_down, port_errors)},
        {"id": "performance", "title": "CPU and memory", "text": _performance_text(window_label, cpu, memory)},
        {"id": "logs", "title": "Logs and config changes", "text": _log_text(window_label, history), "notices": _log_notices(history)},
        {"id": "wifi", "title": "Wi-Fi Network", "text": _wifi_text(grouped["wifi"], clients, noise, interference)},
        {"id": "wan", "title": "SDWAN/WAN Network", "text": _wan_text(window_label, grouped["wan"], wan_known, wan_in, wan_out, loss)},
    ]
    summary = _summary(window_label, devices, grouped, history, cpu, clients, wan_known, wan_in)
    return {
        "window": window_label,
        "summary": summary,
        "sections": sections,
        "talkers": talkers or [],
        "talkerNote": "These are the ports that carried the most traffic in this window. Individual clients are not listed.",
        "sla": sla or {
            "points": [],
            "limiterMbps": None,
            "note": "No SD-WAN or WAN device is recorded at this site.",
        },
    }


def fortigate_limits(inbound_kbps, outbound_kbps) -> dict:
    """Estimated bandwidth statements on the FortiGate, converted from kbps to Mbps.

    A zero is an interface with no statement. Each interface keeps its own
    inbound and outbound figure, because those differ by site and by circuit.
    """

    def by_name(samples) -> dict:
        found = {}
        for sample in samples or []:
            if not isinstance(sample, dict):
                continue
            metric = sample.get("metric") or {}
            name = str(metric.get("ifName") or metric.get("ifDescr") or "").strip()
            value = _value(sample)
            if not name or value is None or value <= 0:
                continue
            found[name] = float(value) / 1000.0
        return found

    inbound = by_name(inbound_kbps)
    outbound = by_name(outbound_kbps)
    interfaces = []
    for name in sorted(set(inbound) | set(outbound)):
        interfaces.append({
            "name": name,
            "inMbps": round(inbound[name], 3) if name in inbound else None,
            "outMbps": round(outbound[name], 3) if name in outbound else None,
        })

    def total(key: str):
        values = [item[key] for item in interfaces if item.get(key)]
        if not values:
            return None
        return round(sum(values), 3)

    return {
        "limiterInMbps": total("inMbps"),
        "limiterOutMbps": total("outMbps"),
        "interfaces": interfaces,
    }


def range_by_name(rows) -> dict:
    """Range-query samples grouped by interface name, then by timestamp."""
    found: dict[str, dict[int, float]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        metric = row.get("metric") or {}
        name = str(metric.get("ifName") or metric.get("ifDescr") or "").strip()
        if not name:
            continue
        series = found.setdefault(name, {})
        for pair in row.get("values") or []:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            try:
                stamp = int(float(pair[0]))
                value = float(pair[1])
            except (TypeError, ValueError):
                continue
            if value < 0 or value != value:
                continue
            series[stamp] = value
    return found


def link_points(inbound_rows, outbound_rows, names: list[str]) -> list[dict]:
    """One throughput series per FortiGate link."""
    inbound = range_by_name(inbound_rows)
    outbound = range_by_name(outbound_rows)
    links = []
    for name in names:
        left = inbound.get(name) or {}
        right = outbound.get(name) or {}
        points = []
        for stamp in sorted(set(left) | set(right)):
            points.append({
                "t": stamp,
                "inMbps": round(left.get(stamp, 0.0), 3),
                "outMbps": round(right.get(stamp, 0.0), 3),
            })
        links.append({"name": name, "points": points})
    return links


def sla_points(inbound, outbound, limiter, limiter_out=None) -> dict:
    """WAN throughput points. Limiter values are Mbps from the caller."""

    def series(rows) -> dict[int, float]:
        found: dict[int, float] = {}
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            for pair in row.get("values") or []:
                if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                    continue
                try:
                    stamp = int(float(pair[0]))
                    value = float(pair[1])
                except (TypeError, ValueError):
                    continue
                if value < 0 or value != value:
                    continue
                found[stamp] = value
        return found

    left = series(inbound)
    right = series(outbound)
    points = []
    for stamp in sorted(set(left) | set(right)):
        moment = datetime.fromtimestamp(stamp, timezone.utc)
        points.append({
            "t": stamp,
            "label": moment.strftime("%H:%M:%S"),
            "inMbps": round(left.get(stamp, 0.0), 3),
            "outMbps": round(right.get(stamp, 0.0), 3),
        })
    def mbps(value):
        try:
            if value is None or float(value) <= 0:
                return None
            return round(float(value), 3)
        except (TypeError, ValueError):
            return None

    limit_in = mbps(limiter)
    limit_out = limit_in if limiter_out is None else mbps(limiter_out)
    single = limit_in if limit_in is not None and limit_in == limit_out else None
    note = "" if points else "No WAN throughput sample arrived in this window."
    return {
        "points": points,
        "limiterMbps": single if single is not None else (limit_in if limit_out is None else None),
        "limiterInMbps": limit_in,
        "limiterOutMbps": limit_out,
        "note": note,
    }


def _summary(window_label, devices, grouped, history, cpu, clients, wan_known, wan_in) -> str:
    if not devices:
        return "This site has no devices yet, so there is no log or performance history to summarise."
    bits = ["Over %s, %s were in view at this site." % (window_label, _count(len(devices), "device"))]
    silent = [device for device in devices if device.get("health") == "unreachable"]
    if silent:
        bits.append("%s %s not answering right now, so their latest SNMP reading is missing." % (
            _count(len(silent), "device"), "is" if len(silent) == 1 else "are",
        ))
    if history["lines"] == 0:
        bits.append("No syslog lines arrived in this window.")
    else:
        bits.append("The logs contain %s." % _count(history["lines"], "line"))
        if history["configChanges"]:
            bits.append("%s showed a config change." % _count(history["configChanges"], "line"))
        if history["linkDown"]:
            bits.append("%s reported a link going down." % _count(history["linkDown"], "line"))
    peak = _peak(cpu)
    if peak:
        bits.append("The highest CPU was %s on %s." % (_pct(peak[1]), peak[0]))
    if clients is not None:
        bits.append("%s %s connected." % (_count(int(round(clients)), "Wi-Fi client"), "is" if int(round(clients)) == 1 else "are"))
    if wan_known and wan_in is not None:
        bits.append("WAN traffic averaged %s in." % _mbps(wan_in))
    return " ".join(bits)


def _lan_text(window_label, devices, ports_down, port_errors) -> str:
    if not devices:
        return "No switches are recorded at this site."
    silent = [device for device in devices if device.get("health") == "unreachable"]
    parts = ["%s %s recorded." % (_count(len(devices), "switch"), "is" if len(devices) == 1 else "are")]
    if silent:
        parts.append("%s %s not answering right now." % (_count(len(silent), "switch"), "is" if len(silent) == 1 else "are"))
    else:
        parts.append("All of them are answering right now.")
    down = _sum(ports_down)
    if ports_down is None:
        parts.append("A current count of down ports was not returned.")
    elif down:
        parts.append("%s %s not connected right now. Unused ports sit in that state, so this alone is not an outage." % (
            _count(int(round(down)), "port"), "is" if int(round(down)) == 1 else "are",
        ))
    else:
        parts.append("No ports were reported down.")
    errors = _sum(port_errors)
    if port_errors is None:
        parts.append("Input errors over %s were not returned." % window_label)
    elif errors:
        top = _peak(port_errors)
        extra = " Most of them were on %s." % top[0] if top else ""
        parts.append("About %s input %s were counted over %s.%s" % (
            _grouped(errors), "error" if errors < 2 else "errors", window_label, extra,
        ))
    else:
        parts.append("No input errors were counted over %s." % window_label)
    return " ".join(parts)


def _performance_text(window_label, cpu, memory) -> str:
    parts = []
    peak = _peak(cpu)
    if cpu is None or not peak:
        parts.append("CPU was not returned for %s." % window_label)
    else:
        parts.append("The highest CPU over %s was %s on %s." % (window_label, _pct(peak[1]), peak[0]))
        if peak[1] >= 90:
            parts.append("That is high enough to slow the device.")
        elif peak[1] >= 75:
            parts.append("That is busy, and worth watching.")
        else:
            parts.append("That is within a comfortable range.")
    mem = _peak(memory)
    if memory is None or not mem:
        parts.append("Memory was not returned.")
    else:
        parts.append("The latest memory reading is %s on %s." % (_pct(mem[1]), mem[0]))
        if mem[1] >= 90:
            parts.append("That device is short on free memory.")
    return " ".join(parts)


def _log_text(window_label, history) -> str:
    if history["lines"] == 0:
        return "No syslog lines arrived from the devices at this site over %s. Performance figures above come from SNMP, not from the logs." % window_label
    parts = ["%s arrived over %s." % (_count(history["lines"], "log line"), window_label)]
    if history["configChanges"] == 0 and history["linkDown"] == 0 and history["linkUp"] == 0 and history["problems"] == 0:
        parts.append("No config change, link change, or error showed up in those lines.")
    elif history["configChanges"] == 0:
        parts.append("No config change showed up in those lines.")
    return " ".join(parts)


def _log_notices(history) -> list[dict]:
    notices = []
    if history["configChanges"]:
        notices.append(_notice(
            "config", "info",
            "%s %s a configuration change" % (
                _count(history["configChanges"], "line"),
                "show" if history["configChanges"] > 1 else "shows",
            ),
            history["configChanges"], history["configItems"],
        ))
    if history["linkDown"]:
        notices.append(_notice(
            "link-down", "warning",
            "%s reported a link down" % _count(history["linkDown"], "line"),
            history["linkDown"], history["linkDownItems"],
        ))
    if history["linkUp"]:
        notices.append(_notice(
            "link-up", "success",
            "%s reported a link up" % _count(history["linkUp"], "line"),
            history["linkUp"], history["linkUpItems"],
        ))
    if history["problems"]:
        notices.append(_notice(
            "problems", "critical",
            "%s %s error or critical severity" % (
                _count(history["problems"], "line"),
                "was" if history["problems"] == 1 else "were",
            ),
            history["problems"], history["problemItems"],
        ))
    return notices


def _notice(note_id: str, tone: str, label: str, total: int, rows: list[dict]) -> dict:
    shown = rows or []
    return {
        "id": note_id,
        "tone": tone,
        "label": label,
        "total": total,
        "items": [_public_item(row) for row in shown],
    }


def _public_item(row: dict) -> dict:
    return {
        "title": row.get("device") or "Device",
        "detail": row.get("message") or "",
        "meta": row.get("at") or "",
    }


def _log_item(line: dict, message: str) -> dict:
    return {
        "at": str(line.get("at") or ""),
        "device": str(line.get("hostname") or ""),
        "message": message[:180],
    }


def _wifi_text(devices, clients, noise, interference) -> str:
    if not devices:
        return "No wireless devices are recorded at this site."
    parts = ["%s %s recorded." % (_count(len(devices), "wireless device"), "is" if len(devices) == 1 else "are")]
    if clients is None:
        parts.append("A client count was not returned. Clients are not listed.")
    else:
        count = int(round(clients))
        parts.append("%s %s connected. Clients are not listed." % (_count(count, "client"), "is" if count == 1 else "are"))
    if noise is None:
        parts.append("Noise was not returned.")
    else:
        parts.append(_noise_sentence(noise))
    if interference is None:
        parts.append("Interference was not returned.")
    else:
        parts.append(_interference_sentence(interference))
    return " ".join(parts)


def _wan_text(window_label, devices, wan_known, wan_in, wan_out, loss) -> str:
    if not devices and not wan_known:
        return "No SD-WAN or WAN device is recorded at this site, so link performance is not monitored here."
    parts = []
    if devices:
        silent = [device for device in devices if device.get("health") == "unreachable"]
        if silent and len(silent) == len(devices):
            parts.append("The WAN %s not answering right now." % ("device is" if len(devices) == 1 else "devices are"))
        else:
            parts.append("The WAN %s answering right now." % ("device is" if len(devices) == 1 else "devices are"))
    if wan_in is None and wan_out is None:
        parts.append("WAN throughput over %s was not returned." % window_label)
    else:
        parts.append("Average traffic over %s was %s in and %s out." % (
            window_label, _mbps(wan_in or 0), _mbps(wan_out or 0),
        ))
    if loss is None:
        parts.append("Loss, latency and jitter were not returned.")
    else:
        shown = loss * 100.0 if abs(loss) <= 1 else loss
        parts.append("The highest tunnel loss reading was %s." % _pct(shown))
    return " ".join(parts)


def _noise_sentence(value: float) -> str:
    shown = round(float(value))
    if shown <= -85:
        return "Average noise is %d dBm, which is a quiet floor." % shown
    if shown >= -80:
        return "Average noise is %d dBm, which is noisy." % shown
    return "Average noise is %d dBm." % shown


def _interference_sentence(value: float) -> str:
    number = float(value)
    if abs(number) <= 1:
        number *= 100.0
    shown = int(round(number))
    if shown <= 10:
        return "Interference is low, about %d%%." % shown
    if shown <= 25:
        return "Interference is moderate, about %d%%." % shown
    return "Interference is high, about %d%%." % shown


def _peak(pairs):
    best = None
    for host, value in pairs or []:
        if best is None or value > best[1]:
            best = (host, value)
    return best


def _sum(pairs) -> float:
    if not pairs:
        return 0.0
    return sum(value for _host, value in pairs)


def _value(sample: dict):
    try:
        return float(sample["value"][1])
    except (KeyError, TypeError, ValueError, IndexError):
        return None


_PLURAL = {
    "switch": "switches",
    "device": "devices",
    "line": "lines",
    "log line": "log lines",
    "port": "ports",
    "wireless device": "wireless devices",
    "client": "clients",
    "Wi-Fi client": "Wi-Fi clients",
}


def _count(number: int, singular: str) -> str:
    number = int(number)
    word = singular if number == 1 else _PLURAL.get(singular, singular + "s")
    return "%d %s" % (number, word)


def _pct(value) -> str:
    return "%d%%" % int(round(float(value)))


def _mbps(value) -> str:
    number = float(value or 0)
    if number >= 1000:
        return "%.1f Gbps" % (number / 1000.0)
    if number >= 10:
        return "%d Mbps" % int(round(number))
    return "%.1f Mbps" % number


def _grouped(value: float) -> str:
    number = int(round(value))
    return "{:,}".format(number)
