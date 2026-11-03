"""Access-point identity and online/offline.

The running collector often has ie_wlc_ap_info and no per-AP oper series.
That info metric is value 1 with the old labels ap, ap_name, ip, mac, source
and wlc. A name label is sometimes the wtp-mac key, so the same AP hostname
can also appear as a MAC. Online means a fresh info or radio sample for that
MAC, unless a capwap state label says the AP is down.

Capwap on a 9800 is periodic at 10 minutes and Telegraf keeps the series for
20 minutes. A sample older than that is not online. When a newer build adds
ap-state / ewlc-ap-state-registered, that text wins over mere presence.
"""

from __future__ import annotations

import re

# 2x the 600s capwap period, and the same window Telegraf uses before it
# expires a series (expiration_interval 20m). Radio-oper is inside this too.
AP_FRESH_SECONDS = 20 * 60

_COLON_MAC = re.compile(r"^([0-9a-f]{2}[:-]){5}[0-9a-f]{2}$")
_CISCO_MAC = re.compile(r"^[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}$")
_STATE_LEAVES = ("ap_operation_state", "ap_state", "oper_state", "operation_state")


def canon_mac(value: str) -> str:
    """Colon form, or empty when the text is a hostname rather than a MAC."""
    text = (value or "").strip().lower()
    if not text:
        return ""
    if _COLON_MAC.match(text):
        return ":".join(re.split(r"[:-]", text))
    if _CISCO_MAC.match(text):
        raw = text.replace(".", "")
        return ":".join(raw[i:i + 2] for i in range(0, 12, 2))
    parts = text.split(".")
    if len(parts) == 6 and all(part.isdigit() and 0 <= int(part) <= 255 for part in parts):
        return ":".join("%02x" % int(part) for part in parts)
    return ""


def looks_like_mac(value: str) -> bool:
    return bool(canon_mac(value))


def interpret_oper_text(value) -> str | None:
    """Map a capwap / AireOS state word. None when the text is not a state."""
    text = str(value or "").strip().lower().replace("_", "-")
    if not text or text in ("unknown", "none", "null"):
        return None
    if "not-registered" in text or "deregister" in text or "disassoc" in text or "ap-down" in text:
        return "down"
    if text in ("down", "offline", "0", "false"):
        return "down"
    if "registered" in text or "ap-up" in text or "associated" in text or text.endswith("-up"):
        return "up"
    if text in ("up", "run", "enabled", "1", "true"):
        return "up"
    return None


def capwap_state(metric: dict) -> str | None:
    """State from a #37-style label, including nested ap_state/ap_operation_state."""
    if not isinstance(metric, dict):
        return None
    for key, value in metric.items():
        if key.startswith("__"):
            continue
        leaf = str(key).replace("-", "_").split("/")[-1]
        if leaf in _STATE_LEAVES:
            found = interpret_oper_text(value)
            if found:
                return found
    return None


def sample_age(sample: dict, now: float) -> float | None:
    pair = sample.get("value") if isinstance(sample, dict) else None
    if not isinstance(pair, (list, tuple)) or not pair:
        return None
    try:
        stamp = float(pair[0])
    except (TypeError, ValueError):
        return None
    return now - stamp


def sample_fresh(sample: dict, now: float, window: float = AP_FRESH_SECONDS) -> bool:
    """A missing timestamp still counts. Prometheus already dropped a dead series."""
    age = sample_age(sample, now)
    if age is None:
        return True
    return 0 <= age <= window


def ap_identity(metric: dict) -> tuple[str, str, str, str]:
    """Hostname, canonical MAC, controller, site.

    ap_name is ignored when it is only the wtp-mac key. wlc falls back to the
    MDT source label used by the collector that is deployed today.
    """
    if not isinstance(metric, dict):
        return "", "", "", ""
    raw_name = str(
        metric.get("ap")
        or metric.get("ap_name")
        or metric.get("bsnAPName")
        or metric.get("cLApName")
        or ""
    ).strip()
    raw_mac = str(
        metric.get("mac")
        or metric.get("wtp_mac")
        or metric.get("ap_mac")
        or metric.get("ethernet_mac")
        or metric.get("wtp_enet_mac")
        or ""
    ).strip()
    # SNMP index is a MAC only when it is six dotted decimals. A radio index
    # has a seventh byte and must not become the AP key.
    if not raw_mac:
        index = str(metric.get("index") or "")
        if canon_mac(index):
            raw_mac = index
    mac = canon_mac(raw_mac) or canon_mac(raw_name)
    name = "" if looks_like_mac(raw_name) else raw_name
    wlc = str(metric.get("wlc") or metric.get("source") or metric.get("agent_host") or "").strip()
    site = str(metric.get("site") or "").strip()
    return name, mac, wlc, site


def explicit_status(metric: dict, value) -> str | None:
    """Numeric oper series, or a state label on the same sample."""
    labeled = capwap_state(metric)
    name = str((metric or {}).get("__name__") or "")
    number = None
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        number = None
    if name.endswith("admin_status") or name.endswith("admin_up"):
        if number == 1:
            return "up"
        if number is not None:
            return "down"
    if "oper_status" in name and "radio" not in name and number is not None:
        # AireOS bsnAPOperationStatus: associated(1) is joined.
        return "up" if number == 1 else "down"
    if name.endswith("oper_up"):
        if number == 1:
            return "up"
        if number == 0:
            return "down"
    if "radio" in name and "oper" in name and number is not None:
        # AireOS radio oper is down(1) / up(2).
        if number == 2:
            return "up"
        if number == 1:
            return "down"
    return labeled


def finish_ap_status(explicit: str | None, fresh: bool) -> str:
    """Down state wins. Otherwise a fresh info or radio sample is online."""
    if explicit == "down":
        return "down"
    if explicit == "up" or fresh:
        return "up"
    return "down"
