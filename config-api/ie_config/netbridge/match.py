"""Match inventory records. Serial wins, then hostname, then management IP.

Hostnames compare with and without HOSTNAME_STRIP_SUFFIXES (for example
.pnp.co.za). A tie at the winning rank is a conflict, not a guess.
"""

from __future__ import annotations

import re

from ie_config.hostnames import strip_hostname

_SERIAL = re.compile(r"[^A-Z0-9]")


def norm_serial(value: str) -> str:
    return _SERIAL.sub("", (value or "").upper())


def host_ip(value: str) -> str:
    return (value or "").split("/")[0].strip()


def name_forms(value: str, suffixes: list[str] | None) -> list[str]:
    forms: list[str] = []
    raw = (value or "").strip().lower()
    if raw:
        forms.append(raw)
    short = strip_hostname(value or "", suffixes).strip().lower()
    if short and short not in forms:
        forms.append(short)
    return forms


def _unique(rows: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for row in rows:
        key = str(row.get("id") or "") or (norm_serial(row.get("serial") or "") + "|" + host_ip(row.get("ip") or "") + "|" + (row.get("name") or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def build_index(devices: list[dict], suffixes: list[str] | None) -> dict:
    by_serial: dict[str, list[dict]] = {}
    by_name: dict[str, list[dict]] = {}
    by_ip: dict[str, list[dict]] = {}
    for device in devices:
        serial = norm_serial(device.get("serial") or "")
        if serial:
            by_serial.setdefault(serial, []).append(device)
        labels = []
        for field in ("name", "hostname", "dns"):
            labels.extend(name_forms(device.get(field) or "", suffixes))
        for label in labels:
            by_name.setdefault(label, []).append(device)
        ip = host_ip(device.get("ip") or "")
        if ip:
            by_ip.setdefault(ip, []).append(device)
    return {"serial": by_serial, "name": by_name, "ip": by_ip}


def match_one(item: dict, index: dict, suffixes: list[str] | None, *, use_ip: bool = True) -> dict:
    """Return {device, via} or {conflict, via, devices} or {device: None, via: ''}."""
    serial = norm_serial(item.get("serial") or "")
    if serial:
        hits = _unique(index["serial"].get(serial) or [])
        if len(hits) == 1:
            return {"device": hits[0], "via": "serial"}
        if len(hits) > 1:
            return {"device": None, "via": "serial", "conflict": "serial", "devices": hits}
    for form in name_forms(item.get("name") or item.get("hostname") or "", suffixes):
        hits = _unique(index["name"].get(form) or [])
        if len(hits) == 1:
            return {"device": hits[0], "via": "hostname"}
        if len(hits) > 1:
            return {"device": None, "via": "hostname", "conflict": "hostname", "devices": hits}
    if use_ip:
        ip = host_ip(item.get("ip") or "")
        if ip:
            hits = _unique(index["ip"].get(ip) or [])
            if len(hits) == 1:
                return {"device": hits[0], "via": "ip"}
            if len(hits) > 1:
                return {"device": None, "via": "ip", "conflict": "ip", "devices": hits}
    return {"device": None, "via": ""}


def names_differ(left: str, right: str, suffixes: list[str] | None) -> bool:
    a = name_forms(left, suffixes)
    b = set(name_forms(right, suffixes))
    if not a or not b:
        return False
    return not any(form in b for form in a)
