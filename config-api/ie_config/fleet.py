"""Fleet API for the customer UI.

NetBox is the inventory (devices, sites, roles, regions). Prometheus holds
reachability, interface counters and CPU/memory. Alertmanager holds alerts.
Writes are alert acknowledge (a silence), adding a wireless access point
to NetBox, and the device-page NetBox sync of model, serial and firmware.
Device health always comes from explain_health.

A fresh NetBox with no devices, and empty Prometheus / Alertmanager, returns
empty lists and zero counts. A down upstream is 502 with
``{"error": {"code": "upstream_unavailable", ...}}`` when the response shape
cannot carry a degraded flag (bare arrays). List and summary responses add
``degraded`` when Prometheus or Alertmanager could not be read and NetBox
itself answered.
"""

from __future__ import annotations

import hmac
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, unquote

import httpx
from fastapi import Request

from .errors import ApiError
from .discovery import NetBoxWriter, _norm_model, catalog_part
from .ap_status import (
    ap_identity as _ap_identity,
    canon_mac,
    capwap_state,
    explicit_status,
    finish_ap_status,
    looks_like_mac,
    sample_fresh,
)
from .health import (
    aireos_psu_states,
    build_health_panel,
    classify_health,
    classify_profile,
    critical_names_from_interfaces,
    explain_health,
    mark_critical_interface,
    match_access_point,
    page_rows,
    suggest_ap_site,
)
from .hostnames import effective_suffixes, names_match, strip_device_label, strip_hostname, suffix_pattern
from .ifnames import canonical_iface, iface_compact, iface_match_keys
from .ifnames import names_match as iface_names_match
from .neighbours import merge_neighbors, neighbors_from_cdp, neighbors_from_lldp

log = logging.getLogger("ie-config.fleet")

FORM_FACTORS = (
    "access-switch-24",
    "access-switch-48",
    "switch-stack",
    "ceiling-ap",
    "wireless-controller",
    "firewall",
    "branch-router",
    "modular-chassis",
    "generic",
)
_HEALTH_RANK = {"healthy": 0, "warning": 1, "critical": 2, "unreachable": 3}
_ROW_SORT = {
    "id", "hostname", "role", "site", "siteId", "mgmtIp", "modelFamily", "health",
    "portsUp", "portsTotal", "portsWarn", "portsFault", "uptime", "lastPoll", "formFactor",
}
_NUMERIC_SORT = {"portsUp", "portsTotal", "portsWarn", "portsFault"}
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MEMBER_RE = re.compile(r"^[A-Za-z]+(\d+)/")
_SILENCE_HOURS = 24
_PAGE_CAP = 40
_ALERT_CAP = 5000


class UpstreamError(Exception):
    def __init__(self, upstream: str, message: str):
        super().__init__(message)
        self.upstream = upstream
        self.message = message


def _as_upstream(exc: UpstreamError) -> ApiError:
    return ApiError(502, "upstream_unavailable", exc.message, {"upstream": exc.upstream})


def _record_netbox_sync(request: Request, user, result: str, detail: str) -> None:
    try:
        from .app import _audit
        from .auth import client_ip
    except Exception:
        return
    sf = getattr(request.app.state, "sf", None)
    if sf is None:
        return
    _audit(sf, user, "netbox-sync", client_ip(request), result, "netbox", "", "", detail)


class _Cache:
    def __init__(self, ttl: float):
        self.ttl = max(0.0, float(ttl))
        self._lock = threading.Lock()
        self._items: dict[str, tuple[float, object]] = {}

    def get(self, key: str):
        if self.ttl <= 0:
            return None
        now = time.monotonic()
        with self._lock:
            hit = self._items.get(key)
            if hit is None:
                return None
            life = hit[2] if len(hit) > 2 else self.ttl
            if now - hit[0] > life:
                self._items.pop(key, None)
                return None
            return hit[1]

    def put(self, key: str, value, ttl: float | None = None):
        if self.ttl <= 0:
            return
        life = self.ttl if ttl is None else max(0.0, float(ttl))
        with self._lock:
            self._items[key] = (time.monotonic(), value, life)

    def drop(self, key: str):
        with self._lock:
            self._items.pop(key, None)

    def drop_prefix(self, prefix: str):
        with self._lock:
            for key in [name for name in self._items if name.startswith(prefix)]:
                self._items.pop(key, None)


def prom_escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "")


def netbox_headers(token_file: str) -> dict:
    """Same token rules as discovery.NetBox calls. The token is never logged."""
    token = ""
    try:
        with open(token_file, "r", encoding="utf-8") as fh:
            token = fh.read().strip()
    except OSError:
        token = ""
    if not token or token == "unset-placeholder":
        return {}
    if token.startswith("nbt_"):
        return {"Authorization": "Bearer " + token, "Accept": "application/json"}
    return {"Authorization": "Token " + token, "Accept": "application/json"}


def webhook_secret(settings) -> str:
    path = getattr(settings, "alert_webhook_token_file", "") or ""
    if path:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                file_token = fh.read().strip()
        except OSError:
            file_token = ""
        if file_token:
            return file_token
    return (os.environ.get("ALERT_WEBHOOK_TOKEN") or "").strip()


def _secret_match(got: str, want: str) -> bool:
    a = got.encode()
    b = want.encode()
    if len(a) != len(b):
        return False
    return hmac.compare_digest(a, b)


def is_form_key(value: str) -> bool:
    """Faceplate sample keys. Hostnames such as fg-edge and pa-edge are devices."""
    return value in FORM_FACTORS


# AP only when the role or the model says so. Hostname prefixes are not a signal:
# "apc-ups" and "apex-" are not access points.
_AP_MODEL = re.compile(
    r"(?i)(?:\bair-ap|\bair-cap|\bair-lap|\bc91\d{2}ax|\bcw91\d{2}|\bfap[-\s]?\d|\baruba\s*ap|\bmeraki\s*mr|\bmr\d{2,3}\b)"
)
_FW_MODEL = re.compile(r"(?i)(fortigate|\bfg-\d|\bpa-\d|\basa-?\d|\bfpr-?\d|firepower)")
_ROUTER_MODEL = re.compile(r"(?i)(\bisr-?\d|\basr-?\d)")
_WLC_MODEL = re.compile(r"(?i)(\bc9800|\bair-ct|\bwlc\b|wireless\s+controller)")
_SWITCH_MODEL = re.compile(r"(?i)(catalyst\s*\d|\bc9[23]\d{2}|\bc2960|\bc3850|\bc3650|\bnexus|\bn9k|fortiswitch)")
# FortiGate copper LAN ports are internal1, internal2, ... The bare name "internal"
# is the software switch. internal(?!\d) keeps Internal-Data virtual and internal1 physical.
_VIRTUAL_NAME = re.compile(
    r"(?i)^(vlan|vl\d|loopback|lo\d*|null\d*|tunnel|tu\d|bdi|nve|port-channel|po\d|cpu|stackport|internal(?!\d))"
)
_FORM_KIND = {
    "access-switch-24": "switch",
    "access-switch-48": "switch",
    "switch-stack": "stack",
    "ceiling-ap": "ap",
    "wireless-controller": "controller",
    "firewall": "firewall",
    "branch-router": "router",
    "modular-chassis": "chassis",
    "generic": "generic",
}


def _role_form(role_slug: str, role_name: str, model: str) -> tuple[str, str]:
    """Role and model text only. Same order the faceplate used before classify_device."""
    slug = (role_slug or "").strip().lower()
    name = (role_name or "").strip()
    blob = " ".join((slug, name.lower(), (model or "").lower()))
    if "stack" in blob:
        return "Switch stack", "switch-stack"
    if slug in ("access-point", "ap") or "access point" in blob or "access-point" in blob:
        return "Access point", "ceiling-ap"
    if "wireless" in blob or slug in ("wlc", "wireless-controller"):
        return "Wireless controller", "wireless-controller"
    if any(part in blob for part in ("firewall", "sdwan", "fortigate", "palo")) or slug in ("hub", "sdwan", "core-firewall"):
        return "Firewall", "firewall"
    if "router" in blob:
        return "Branch router", "branch-router"
    if "chassis" in blob or slug in ("core-switch", "modular-chassis"):
        return "Modular chassis", "modular-chassis"
    if "distribution" in blob:
        return "Switch stack", "switch-stack"
    if "access" in blob or "switch" in blob:
        form = "access-switch-24" if re.search(r"(^|[^0-9])24([^0-9]|$)", model or "") else "access-switch-48"
        return "Access switch", form
    display = name or role_slug or "Unclassified"
    return display, "generic"


def _size_from_model(model: str) -> str:
    text = model or ""
    if re.search(r"(^|[^0-9])24([^0-9]|$)", text) or re.search(r"(^|[^0-9])(8|12)([^0-9]|$)", text):
        return "access-switch-24"
    return "access-switch-48"


def _mbps(value) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        return number / 1_000_000.0 if number >= 100_000 else number
    text = str(value).strip().lower().replace(",", "")
    match = re.search(r"([\d.]+)\s*([gmk])?", text)
    if not match:
        return 0.0
    try:
        number = float(match.group(1))
    except ValueError:
        return 0.0
    unit = match.group(2) or ""
    if unit == "g":
        return number * 1000.0
    if unit == "k":
        return number / 1000.0
    if not unit and number >= 100_000:
        return number / 1_000_000.0
    return number


def port_medium(name: str, type_text: str = "", mbps: float = 0) -> str:
    """Copper or optic from the port type, speed and name."""
    blob = "%s %s" % (name or "", type_text or "")
    low = blob.lower()
    if "console" in low:
        return "CONSOLE"
    if "usb" in low:
        return "USB"
    if "mgmt" in low or "management" in low or low.strip().startswith("fxp"):
        return "MGMT"
    if "base-t" in low or "rj45" in low:
        return "RJ45"
    if "qsfp" in low or "40gbase" in low or "100gbase" in low or (mbps and mbps >= 40000):
        return "QSFP"
    if any(part in low for part in ("sfp+", "sfp28", "10gbase", "sfpp", "25gbase")) or (mbps and mbps >= 10000):
        return "SFP+"
    if any(part in low for part in ("sfp", "base-x", "base-sr", "base-lr", "fiber", "fibre")):
        return "SFP"
    named = port_type_for(name or "")
    return named


def _is_radio(name: str, type_text: str = "") -> bool:
    blob = "%s %s" % (name or "", type_text or "")
    low = blob.lower()
    return any(token in low for token in ("radio", "dot11", "802.11", "wlan"))


def _is_access_point_interface(name: str, type_text: str = "") -> bool:
    """A joined access point or its radio, not the socket a cable plugs into.

    AppGigabitEthernet is the switch port the access-point cable uses, so it stays.
    """
    low = (name or "").strip().lower()
    if _is_radio(name, type_text):
        return True
    if re.search(r"(^|[^a-z0-9])(capwap|lwapp)([^a-z0-9]|$)", low):
        return True
    return bool(re.match(r"^(ap|access-point)[-_]?\d+$", low))


def _is_virtual_port(name: str, type_text: str = "") -> bool:
    low_type = (type_text or "").lower()
    if low_type in ("virtual", "lag", "bridge") or "virtual" in low_type:
        return True
    return bool(_VIRTUAL_NAME.match(name or ""))


def _norm_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _clean_inventory(value: str, limit: int = 64) -> str:
    text = re.sub(r"\s+", " ", (value or "").strip().rstrip("$")).strip()
    return text[:limit]


def _fit_serial(value: str) -> str:
    """NetBox stores one serial of at most 50 characters. A stack keeps the first chassis serial."""
    text = _clean_inventory(value, 200)
    if len(text) <= 50:
        return text
    return text.split(",")[0].strip()[:50]


def _first_text(*values: str) -> str:
    for value in values:
        if value:
            return value
    return ""


def live_inventory(snmp: dict | None, netdisco: dict | None, ap: dict | None = None) -> dict:
    """Model, serial and firmware to store. The device's own SNMP report wins, then the controller, then Netdisco."""
    snmp = snmp or {}
    nd = netdisco or {}
    ap = ap or {}
    nd_firmware = _clean_inventory(str(nd.get("firmware") or ""))
    if not nd_firmware:
        nd_firmware = _clean_inventory(" ".join(part for part in (str(nd.get("os") or ""), str(nd.get("os_ver") or "")) if part))
    return {
        "model": _first_text(
            catalog_part(str(snmp.get("part") or "")),
            catalog_part(str(ap.get("model") or "")),
            catalog_part(str(nd.get("model") or "")),
        ),
        "serial": _first_text(
            _fit_serial(str(snmp.get("serial") or "")),
            _fit_serial(str(ap.get("serial") or "")),
            _fit_serial(str(nd.get("serial") or "")),
        ),
        "firmware": _first_text(
            _clean_inventory(str(snmp.get("firmware") or "")),
            _clean_inventory(str(ap.get("ios") or "")),
            nd_firmware,
        ),
    }


def live_model_names(snmp: dict | None, netdisco: dict | None, ap: dict | None = None) -> list[str]:
    snmp = snmp or {}
    nd = netdisco or {}
    ap = ap or {}
    names = []
    for raw in (snmp.get("part"), (ap or {}).get("model"), nd.get("model")):
        text = catalog_part(str(raw or "")) or _clean_inventory(str(raw or ""))
        if text and text not in names:
            names.append(text)
    return names


def _device_type_matches(found: dict | None, name: str) -> bool:
    wanted = _norm_model(name)
    if not wanted or not isinstance(found, dict):
        return False
    return any(_norm_model(str(found.get(field) or "")) == wanted for field in ("model", "part_number", "slug"))


def _pick_device_type(writer, manufacturer_id, names: list[str], current_type: dict) -> tuple[dict | None, str]:
    """An existing library type whose model or part number is the live model. Never creates a type."""
    if not names:
        return None, ""
    for name in names:
        if _device_type_matches(current_type, name):
            return None, ""
        found = writer.find_device_type(manufacturer_id, name, {}) if manufacturer_id else None
        if _device_type_matches(found, name):
            current_id = current_type.get("id") if isinstance(current_type, dict) else None
            if current_id is not None and str(found.get("id")) == str(current_id):
                return None, ""
            return found, ""
    return None, "No NetBox device type matches %s." % names[0]


def inventory_patch(current: dict, live: dict, matched_type: dict | None) -> tuple[dict, list[str]]:
    """PATCH body for model, serial and firmware. Empty live values are left untouched."""
    body: dict = {}
    updated: list[str] = []
    if isinstance(matched_type, dict) and matched_type.get("id") not in (None, ""):
        dtype = current.get("device_type") if isinstance(current.get("device_type"), dict) else {}
        current_id = dtype.get("id") if dtype else current.get("device_type")
        try:
            same = int(matched_type["id"]) == int(current_id)
        except (TypeError, ValueError):
            same = False
        if not same:
            body["device_type"] = int(matched_type["id"])
            updated.append("model")
    serial = _fit_serial(str(live.get("serial") or ""))
    if serial and _norm_text(serial) != _norm_text(str(current.get("serial") or "")):
        body["serial"] = serial
        updated.append("serial")
    firmware = _clean_inventory(str(live.get("firmware") or ""))
    custom = current.get("custom_fields") if isinstance(current.get("custom_fields"), dict) else {}
    if firmware and _norm_text(firmware) != _norm_text(_clean_inventory(str(custom.get("ie_sw_version") or ""))):
        body["custom_fields"] = {"ie_sw_version": firmware}
        updated.append("firmware")
    return body, updated


def _port_name(port: dict) -> str:
    return str(port.get("name") or port.get("port") or "")


_KNOWN_IFACE = re.compile(r"^(fa|gi|te|fo|hu|twe|eth|et|po|vl|lo|tu|mgmt|ma|ae|nu|port|wan|ha)\d")


def _is_iface_spelling(value: str) -> bool:
    """True when the text is a long or short interface name, not a description."""
    text = (value or "").strip()
    if not text or " " in text:
        return False
    compact = iface_compact(text)
    canon = canonical_iface(text)
    if not canon:
        return False
    if canon != compact:
        return True
    return bool(_KNOWN_IFACE.match(canon))


def _looks_like_name(value: str) -> bool:
    text = (value or "").strip()
    if not text or " " in text or len(text) > 48:
        return False
    if _is_iface_spelling(text):
        return True
    # Bl0/4 and Bluetooth0/4. A label such as TILL19 is a description, not a name.
    return bool(re.match(r"^[a-z]{1,20}\d+([/.]\d+)+$", iface_compact(text)))


_NAME_TOKEN = re.compile(r"^([a-z]{2,20})(\d+(?:[/.]\d+)*)$")


def _same_port_name(left: str, right: str) -> bool:
    """FastEthernet0/21, Fa0/21, Bl0/4 / Bluetooth0/4 and Nu0 / Null0 are one interface."""
    if not left or not right:
        return False
    if iface_names_match(left, right):
        return True
    if _is_iface_spelling(left) and _is_iface_spelling(right):
        return False
    token_left = _NAME_TOKEN.match(iface_compact(left))
    token_right = _NAME_TOKEN.match(iface_compact(right))
    if not token_left or not token_right or token_left.group(2) != token_right.group(2):
        return False
    prefix_left = token_left.group(1)
    prefix_right = token_right.group(1)
    short, longer = (prefix_left, prefix_right) if len(prefix_left) <= len(prefix_right) else (prefix_right, prefix_left)
    return len(short) >= 2 and longer.startswith(short)


def _interface_texts(port: dict) -> list[str]:
    texts: list[str] = []

    def add(value) -> None:
        text = str(value or "").strip()
        if text and text not in texts:
            texts.append(text)

    add(port.get("name"))
    add(port.get("port"))
    add(port.get("ifName"))
    for item in port.get("names") or []:
        add(item)
    add(port.get("description"))
    add(port.get("descr"))
    add(port.get("alias"))
    return texts


def _interface_fields(port: dict, prom: dict | None = None) -> dict:
    """Other spellings of the interface name, and the configured description.

    Fa0/21 and FastEthernet0/21 are names. ifAlias, or the NetBox/Netdisco
    description, is the description when it is not another spelling of the name.
    A live ifAlias wins over the inventory description.
    """
    primary = str(port.get("name") or port.get("port") or "").strip()
    texts = _interface_texts(port)
    if prom:
        for text in _interface_texts(prom):
            if text not in texts:
                texts.append(text)
    anchor = ""
    for text in texts:
        if _looks_like_name(text):
            anchor = text
            break
    if not anchor:
        anchor = primary
    spellings: list[str] = []
    loose: list[str] = []
    for text in texts:
        if anchor and _same_port_name(text, anchor):
            if text not in spellings:
                spellings.append(text)
        elif text not in loose:
            loose.append(text)
    alias = str((prom or {}).get("alias") or port.get("alias") or "").strip()
    description = ""
    # Keep a description that was stored as the port name (NetBox "TILL19").
    primary_is_name = bool(primary) and _same_port_name(primary, anchor or primary)
    if alias and not _same_port_name(alias, anchor or primary):
        description = alias
    else:
        for text in loose:
            if primary and text.lower() == primary.lower() and primary_is_name:
                continue
            if anchor and _same_port_name(text, anchor):
                continue
            description = text
            break
    extras = [item for item in spellings if not primary or item.lower() != primary.lower()]
    return {"names": extras, "description": description}


def _present_port(port: dict) -> dict:
    """Copy a Prometheus port so the description is ifAlias, not ifDescr."""
    shown = dict(port)
    fields = _interface_fields(port)
    shown["names"] = fields["names"]
    if fields["description"]:
        shown["description"] = fields["description"]
    else:
        shown.pop("description", None)
    return shown


def _port_type_text(port: dict) -> str:
    kind = port.get("type")
    if isinstance(kind, dict):
        return str(kind.get("label") or kind.get("value") or "")
    return str(kind or "")


def _is_physical(port: dict) -> bool:
    return not _is_virtual_port(_port_name(port), _port_type_text(port))


def _medium_of(port: dict) -> str:
    stored = port.get("medium")
    if stored in ("RJ45", "SFP", "SFP+", "QSFP", "MGMT", "CONSOLE", "USB"):
        return stored
    return port_medium(_port_name(port), _port_type_text(port), _mbps(port.get("speed")))


def _is_cable_port(port: dict) -> bool:
    """A faceplate opening where a network cable connects. Radios and access points are not ports."""
    name = _port_name(port)
    kind = _port_type_text(port)
    if not _is_physical(port) or _is_access_point_interface(name, kind):
        return False
    return _medium_of(port) not in ("CONSOLE", "USB")


def _ethernet_ports(ports: list[dict]) -> list[dict]:
    return [port for port in ports or [] if _is_cable_port(port)]


def _copper_count(ports: list[dict]) -> int:
    return sum(1 for port in _ethernet_ports(ports) if _medium_of(port) == "RJ45")


def _switch_sized(ports: list[dict]) -> bool:
    return len(_ethernet_ports(ports)) >= 8


def _ap_shaped(ports: list[dict]) -> bool:
    if not ports:
        return False
    radios = [port for port in ports if _is_physical(port) and _is_radio(_port_name(port), _port_type_text(port))]
    return len(radios) >= 1 and len(_ethernet_ports(ports)) <= 2


def _is_stack(ports: list[dict], role_blob: str, model: str) -> bool:
    blob = "%s %s" % (role_blob or "", model or "")
    if "stack" in blob.lower() or "distribution" in blob.lower():
        return True
    members = set()
    for port in ports or []:
        match = _MEMBER_RE.match(_port_name(port))
        if match:
            members.add(int(match.group(1)))
    return len(members) >= 2


def _switch_form_from_ports(ports: list[dict], model: str) -> str:
    if _is_stack(ports, "", model):
        return "switch-stack"
    copper = _copper_count(ports)
    if copper <= 0:
        return _size_from_model(model)
    if copper <= 28:
        return "access-switch-24"
    return "access-switch-48"


def _canonical_port(port: dict, fallback_state: str = "down") -> dict:
    name = _port_name(port)
    mbps = _mbps(port.get("speed"))
    medium = _medium_of(port)
    admin = str(port.get("admin") or port.get("up_admin") or "").lower()
    oper = str(port.get("up") or port.get("state") or "").lower()
    if port.get("enabled") is False or admin in ("down", "disabled", "off"):
        state = "disabled"
    elif oper in ("up", "true", "1"):
        state = "up"
    elif oper in ("warning", "fault", "down", "false", "0"):
        state = oper if oper in ("warning", "fault", "down") else "down"
    elif port.get("enabled") is True and not oper:
        # Enabled in NetBox is admin state, not link state. Without an oper
        # value the port is unconfirmed and must not be drawn as up.
        state = "unknown"
    else:
        state = fallback_state
    built = {
        "id": str(port.get("id") or name),
        "name": name,
        "type": medium if medium in ("RJ45", "SFP", "SFP+", "QSFP", "MGMT", "CONSOLE", "USB") else "RJ45",
        "speed": speed_text(mbps, state),
        "state": state,
        "utilisation": float(port.get("utilisation") or 0),
        "errors": int(port.get("errors") or 0),
    }
    remote = str(port.get("remoteName") or port.get("remote_id") or "")
    remote_port = str(port.get("remotePort") or port.get("remote_port") or "")
    remote_ip = str(port.get("remoteAddress") or "")
    if remote or remote_ip:
        built["neighbour"] = {
            "device": remote or remote_ip,
            "port": remote_port,
            "deviceId": str(port.get("deviceId") or ""),
        }
    fields = _interface_fields(port)
    if fields["names"]:
        built["names"] = fields["names"]
    if fields["description"]:
        built["description"] = fields["description"]
    return built


def _inventory_ports(rows: list[dict] | None) -> list[dict]:
    ports = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if _is_virtual_port(_port_name(row), _port_type_text(row)):
            continue
        ports.append(_canonical_port(row))
    return ports


def _comparison_side(vendor: str, model: str, serial: str, os_name: str, port_count: int, site: str = "", firmware: str = "") -> dict:
    return {
        "vendor": vendor or "",
        "model": model or "",
        "serial": (serial or "").strip(),
        "os": os_name or "",
        "portCount": int(port_count or 0),
        "site": site or "",
        "firmware": firmware or "",
    }


def _sides_differ(netbox_side: dict, netdisco_side: dict, raw_netbox: dict, raw_netdisco: dict) -> bool:
    nb_ports = int(netbox_side.get("portCount") or 0)
    nd_ports = int(netdisco_side.get("portCount") or 0)
    if nb_ports > 0 and nd_ports > 0 and nb_ports != nd_ports:
        return True
    for key in ("vendor", "model", "os"):
        left = _norm_text(netbox_side.get(key) or "")
        right = _norm_text(netdisco_side.get(key) or "")
        if left and right and left != right:
            return True
    left_serial = _norm_text(raw_netbox.get("serial") or "")
    right_serial = _norm_text(raw_netdisco.get("serial") or "")
    if left_serial and right_serial and left_serial != right_serial:
        return True
    return False


def classify_device(netbox: dict | None, netdisco: dict | None) -> dict:
    """Choose a faceplate class from NetBox role and device type, then Netdisco.

    NetBox role, manufacturer and model are the first signal. Netdisco vendor,
    model, sysDescr and the port list cross-check that. An access point is
    returned only when the role or the model says so, or when the port list is
    one or two ethernet uplinks plus radios. Anything else unknown is generic
    and keeps its real ports. A hostname such as apc-ups is not an access point.
    When both sides have a port count and they disagree, the faceplate uses
    the Netdisco ports.
    """
    nb = netbox or {}
    nd = netdisco or {}
    role_slug = str(nb.get("role_slug") or "")
    role_name = str(nb.get("role_name") or "")
    manufacturer = str(nb.get("manufacturer") or "")
    model = str(nb.get("model") or "")
    nd_model = str(nd.get("model") or "")
    nd_vendor = str(nd.get("vendor") or "")
    description = str(nd.get("description") or nd.get("sysDescr") or "")
    device_blob = " ".join(part for part in (manufacturer, model, nd_vendor, nd_model, description) if part)
    role_blob = " ".join((role_slug.lower(), role_name.lower()))
    # Role classification uses the NetBox model only. Netdisco model and sysDescr
    # are applied afterwards so a disagreeing discovery record can correct it.
    display, form = _role_form(role_slug, role_name, model)
    nb_ports = _inventory_ports(nb.get("interfaces") if isinstance(nb.get("interfaces"), list) else nb.get("ports"))
    nd_ports = _inventory_ports(nd.get("ports") if isinstance(nd.get("ports"), list) else None)
    evidence = nd_ports or nb_ports
    ap_model = bool(_AP_MODEL.search(device_blob))
    if ap_model and not _switch_sized(evidence):
        display, form = "Access point", "ceiling-ap"
    elif _FW_MODEL.search(device_blob) or (
        form == "generic" and any(token in device_blob.lower() for token in ("fortinet", "palo alto", "paloalto"))
        and "fortiswitch" not in device_blob.lower()
    ):
        display, form = "Firewall", "firewall"
    elif _ROUTER_MODEL.search(device_blob) and form in ("generic", "access-switch-24", "access-switch-48"):
        display, form = "Branch router", "branch-router"
    elif _WLC_MODEL.search(device_blob) and form == "generic":
        display, form = "Wireless controller", "wireless-controller"
    elif form == "generic" and _SWITCH_MODEL.search(device_blob):
        display, form = "Access switch", _size_from_model(model or nd_model)
    port_count_hint = 0
    try:
        port_count_hint = int(nd.get("port_count") or 0)
    except (TypeError, ValueError):
        port_count_hint = 0
    if form == "ceiling-ap" and not ap_model:
        if _switch_sized(evidence) or port_count_hint >= 12:
            display, form = "Access switch", _switch_form_from_ports(evidence, model or nd_model) if evidence else _size_from_model(model or nd_model)
        elif not (role_slug.lower() in ("access-point", "ap") or "access point" in role_blob or "access-point" in role_blob):
            display, form = "Unclassified", "generic"
    elif form == "generic" and _ap_shaped(evidence):
        display, form = "Access point", "ceiling-ap"
    elif form == "generic" and (_switch_sized(evidence) or port_count_hint >= 12):
        display, form = "Access switch", _switch_form_from_ports(evidence, model or nd_model) if evidence else _size_from_model(model or nd_model)
    if form in ("access-switch-24", "access-switch-48") and evidence and _is_stack(evidence, role_blob, model or nd_model):
        form = "switch-stack"
        display = "Switch stack"
    elif form in ("access-switch-24", "access-switch-48") and evidence and nd_ports:
        form = _switch_form_from_ports(nd_ports, nd_model or model)
        if form == "switch-stack":
            display = "Switch stack"
        else:
            display = "Access switch"
    if form not in FORM_FACTORS:
        form = "generic"
    nb_count = len(nb_ports)
    nd_count = len(nd_ports) if nd_ports else (port_count_hint if not nd.get("ports") else 0)
    # The faceplate shows NetBox's physical ports. Netdisco fills in only when NetBox has none.
    if nb_ports:
        face_ports = _ethernet_ports(nb_ports)
        source = "netbox"
    elif nd_ports:
        face_ports = _ethernet_ports(nd_ports)
        source = "netdisco"
    else:
        face_ports = []
        source = "none"
    os_nd = " ".join(part for part in (str(nd.get("os") or ""), str(nd.get("os_ver") or "")) if part).strip()
    raw_nb = {"serial": str(nb.get("serial") or "")}
    raw_nd = {"serial": str(nd.get("serial") or "")}
    nb_firmware = str(nb.get("sw_version") or nb.get("platform") or "").strip().rstrip("$")
    shown_model = str(nb.get("part_number") or "").strip() or model
    nb_side = _comparison_side(manufacturer, shown_model, raw_nb["serial"], str(nb.get("platform") or ""), nb_count, str(nb.get("site") or ""), nb_firmware)
    nb_side["partNumber"] = str(nb.get("part_number") or "")
    nd_side = _comparison_side(nd_vendor, nd_model, raw_nd["serial"], os_nd, nd_count if nd_count else len(nd_ports), str(nd.get("location") or ""), os_nd)
    differ = _sides_differ(nb_side, nd_side, raw_nb, raw_nd)
    return {
        "role": display,
        "form": form,
        "kind": _FORM_KIND.get(form, "generic"),
        "faceplate_source": source,
        "ports": face_ports,
        "comparison": {
            "netbox": nb_side,
            "netdisco": nd_side,
            "faceplateSource": source,
            "differ": differ,
        },
    }


def form_factor_for(role_slug: str, role_name: str, model: str) -> tuple[str, str]:
    """Map a NetBox role and model to the UI display role and faceplate form factor."""
    result = classify_device(
        {"role_slug": role_slug, "role_name": role_name, "model": model, "manufacturer": "", "hostname": ""},
        None,
    )
    return result["role"], result["form"]


def _alert_health(alert: dict) -> dict:
    return {
        "id": alert.get("id") or "",
        "severity": alert.get("severity") or "warning",
        "title": alert.get("title") or "Alert",
        "detail": alert.get("detail") or "",
        "status": alert.get("status") or "open",
        "ageSeconds": int(alert.get("ageMinutes") or 0) * 60,
        "target": alert.get("deviceHostname") or alert.get("category") or "device",
        "deviceHostname": alert.get("deviceHostname") or "",
    }


def _basic_switch(row: dict) -> bool:
    """2960, 3560, C1000, SG350 and SG500 do not contribute fan, power or temperature."""
    device = row.get("_device") or {}
    return classify_profile(
        row.get("role_slug") or row.get("role") or "",
        device.get("platform") or "",
        device.get("manufacturer") or "",
        device.get("model") or "",
    ) == "ios-basic"


def _row_health_snapshot(row: dict, alerts: list[dict]) -> dict:
    age = row.get("last_age")
    if age is not None and age >= 10**12:
        age = None
    snap = {
        "probe": row.get("_probe"),
        "snmpUp": row.get("_snmp"),
        "lastAgeS": age,
        "portsFault": row.get("portsFault") or 0,
        "portsWarn": row.get("portsWarn") or 0,
        "portsTotal": row.get("portsTotal") or 0,
        "since": row.get("lastPoll") or "—",
        "alerts": [_alert_health(alert) for alert in alerts or []],
    }
    if row.get("_cpu") is not None:
        snap["cpu"] = row["_cpu"]
    if row.get("_memory") is not None:
        snap["memoryRatio"] = row["_memory"]
    if not _basic_switch(row):
        if row.get("_temp") is not None:
            snap["tempC"] = row["_temp"]
        if row.get("_fan_ok") is not None:
            snap["fanOk"] = row["_fan_ok"]
        if row.get("_psu_ok") is not None:
            snap["psuOk"] = row["_psu_ok"]
    return snap


def worst_health(values: list[str]) -> str:
    if not values:
        return "healthy"
    return max(values, key=lambda item: _HEALTH_RANK.get(item, 0))


def display_serial(serial: str) -> str:
    parts = [item.strip() for item in (serial or "").split(",") if item.strip()]
    return ", ".join(parts) if parts else "—"


def mask_serial(serial: str) -> str:
    text = (serial or "").strip()
    if not text:
        return "—"
    if len(text) <= 4:
        return "•" * len(text)
    return text[:3] + ("•" * max(4, len(text) - 6)) + text[-3:]


_LABEL_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)="((?:\\.|[^"\\])*)"')
_VERSION_RE = re.compile(r"Version\s+([^,\s]+)", re.I)
_VERSION_TOKEN_RE = re.compile(r"\d+\.\d[\w.()]*")
_OPTIC_RE = re.compile(r"^(SFP|GLC|QSFP|CVR|MA-|X2-)", re.I)


def _metric_lines(text: str) -> list[str]:
    """Keep a quoted label together. IOS-XE sysDescr embeds a carriage return, which splitlines() treats as a new row and cuts the version off."""
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "")
    lines = []
    pending = ""
    for raw in normalized.split("\n"):
        pending = (pending + "\\n" + raw) if pending else raw
        if pending.count('"') % 2 == 1:
            continue
        lines.append(pending)
        pending = ""
    if pending:
        lines.append(pending)
    return lines


def _firmware_token(software: str) -> str:
    cleaned = (software or "").rstrip("$").strip()
    if not cleaned:
        return ""
    if " " not in cleaned:
        return cleaned
    # IOS-XE entity software is "Bengaluru 17.06.03" or "Dublin 17.12.05".
    match = _VERSION_TOKEN_RE.search(cleaned)
    return match.group(0).rstrip(".") if match else ""


def parse_system_metrics(text: str) -> dict:
    """sysUpTime, IOS version, chassis part number and chassis serial from an snmp_exporter scrape."""
    uptime = None
    descr = ""
    parts = []
    for raw in _metric_lines(text):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("sysUpTime"):
            try:
                uptime = float(line.split()[-1])
            except (TypeError, ValueError):
                pass
            continue
        if "{" not in line:
            continue
        name, _rest = line.split("{", 1)
        labels = {
            key: value.replace("\\n", "\n").replace('\\"', '"')
            for key, value in _LABEL_RE.findall(line)
        }
        if name == "sysDescr":
            descr = labels.get("sysDescr") or descr
        elif name == "entPhysicalModelName":
            model = (labels.get("entPhysicalModelName") or "").strip()
            if model and not _OPTIC_RE.match(model):
                parts.append((
                    model,
                    (labels.get("entPhysicalSoftwareRev") or "").strip(),
                    (labels.get("entPhysicalSerialNum") or "").strip(),
                ))
    version = ""
    match = _VERSION_RE.search(descr.replace("\n", " "))
    if match:
        version = match.group(1).strip().rstrip("$")
    part = ""
    ranked = sorted(parts, key=lambda item: (0 if item[2] else 1, 0 if item[1] else 1, len(item[0])))
    if ranked:
        part = ranked[0][0]
    if not version:
        ordered = [item for item in parts if item[0] == part] + parts
        for _model, software, _serial in ordered:
            version = _firmware_token(software)
            if version:
                break
    serials = []
    seen = set()
    for model, _software, serial in parts:
        if part and model != part:
            continue
        if not serial or serial in seen:
            continue
        seen.add(serial)
        serials.append(serial)
    if not serials:
        for _model, _software, serial in ranked:
            if serial and serial not in seen:
                serials.append(serial)
                break
    return {"uptime": uptime, "firmware": version, "part": part, "serial": ", ".join(serials)}


def parse_resource_metrics(text: str) -> dict:
    """CPU percent and memory used percent from a cisco_pro/cisco_mem or FortiGate scrape."""
    series: dict[str, list[float]] = {}
    used = 0.0
    free = 0.0
    pools = 0
    for raw in _metric_lines(text):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name = line.split("{", 1)[0].split()[0]
        try:
            value = float(line.split()[-1])
        except (TypeError, ValueError):
            continue
        if name in ("cpmCPUTotal5minRev", "cpmCPUTotal5min", "fgSysCpuUsage", "fgSysMemUsage"):
            series.setdefault(name, []).append(value)
        elif name == "ciscoMemoryPoolUsed":
            used += value
            pools += 1
        elif name == "ciscoMemoryPoolFree":
            free += value
    cpu = None
    for key in ("cpmCPUTotal5minRev", "cpmCPUTotal5min", "fgSysCpuUsage"):
        if series.get(key):
            cpu = sum(series[key]) / len(series[key])
            break
    memory = None
    if pools and (used + free) > 0:
        memory = used / (used + free) * 100.0
    elif series.get("fgSysMemUsage"):
        memory = sum(series["fgSysMemUsage"]) / len(series["fgSysMemUsage"])
    return {"cpu": cpu, "mem": memory}


def format_uptime(timeticks) -> tuple[str, float]:
    try:
        raw = float(timeticks)
    except (TypeError, ValueError):
        return "—", -1.0
    # snmp_exporter leaves sysUpTime in hundredths of a second (see alert rules).
    seconds = raw / 100.0
    if seconds < 0:
        seconds = 0
    whole = int(seconds)
    days, rem = divmod(whole, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _sec = divmod(rem, 60)
    if days:
        return "%dd %02dh" % (days, hours), seconds
    if hours:
        return "%dh %02dm" % (hours, minutes), seconds
    return "%dm" % minutes, seconds


def format_ago(age_s) -> str:
    if age_s is None:
        return "—"
    try:
        whole = max(0, int(age_s))
    except (TypeError, ValueError):
        return "—"
    if whole < 60:
        return "%ds ago" % whole
    minutes, seconds = divmod(whole, 60)
    if minutes < 60:
        return "%dm %ds ago" % (minutes, seconds) if seconds else "%dm ago" % minutes
    hours, minutes = divmod(minutes, 60)
    if hours < 48:
        return "%dh %dm ago" % (hours, minutes)
    days, hours = divmod(hours, 24)
    return "%dd %dh ago" % (days, hours)


def _parse_time(value: str) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M")


def _clock_stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def port_type_for(name: str) -> str:
    low = (name or "").lower()
    if "console" in low or low.startswith("con"):
        return "CONSOLE"
    if "usb" in low:
        return "USB"
    if "mgmt" in low or "management" in low:
        return "MGMT"
    if low.startswith(("hu", "fo", "qsfp")) or "qsfp" in low:
        return "QSFP"
    if low.startswith(("te", "twe")) or "sfp+" in low or "ten" in low:
        return "SFP+"
    if low.startswith("sf") or "sfp" in low:
        return "SFP"
    return "RJ45"


def speed_text(mbps, state: str) -> str:
    if state in ("down", "disabled") or not mbps:
        return "—"
    try:
        value = float(mbps)
    except (TypeError, ValueError):
        return "—"
    if value <= 0:
        return "—"
    if value >= 1000:
        giga = value / 1000.0
        if abs(giga - round(giga)) < 0.05:
            return "%d Gbps" % int(round(giga))
        return "%.1f Gbps" % giga
    return "%d Mbps" % int(round(value))


def _sample_value(sample: dict):
    try:
        return float(sample["value"][1])
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def _index_samples(samples: list[dict]) -> tuple[dict, dict]:
    by_host: dict[str, float] = {}
    by_ip: dict[str, float] = {}
    for sample in samples or []:
        metric = sample.get("metric") or {}
        value = _sample_value(sample)
        if value is None:
            continue
        host = str(metric.get("hostname") or metric.get("device") or "").strip().lower()
        ip = str(metric.get("instance") or metric.get("ipv4") or "").split(":")[0].strip()
        if host:
            by_host[host] = max(by_host.get(host, value), value) if host in by_host else value
        if ip:
            by_ip[ip] = max(by_ip.get(ip, value), value) if ip in by_ip else value
    return by_host, by_ip


def _index_min(samples: list[dict]) -> tuple[dict, dict]:
    by_host: dict[str, float] = {}
    by_ip: dict[str, float] = {}
    for sample in samples or []:
        metric = sample.get("metric") or {}
        value = _sample_value(sample)
        if value is None:
            continue
        host = str(metric.get("hostname") or metric.get("device") or "").strip().lower()
        ip = str(metric.get("instance") or metric.get("ipv4") or "").split(":")[0].strip()
        if host:
            by_host[host] = value if host not in by_host else min(by_host[host], value)
        if ip:
            by_ip[ip] = value if ip not in by_ip else min(by_ip[ip], value)
    return by_host, by_ip


def _lookup(pair: tuple[dict, dict], host: str, ip: str):
    by_host, by_ip = pair
    if host and host.lower() in by_host:
        return by_host[host.lower()]
    if ip and ip in by_ip:
        return by_ip[ip]
    return None


def _city(raw: dict) -> str:
    address = raw.get("physical_address") or ""
    if not isinstance(address, str) or not address.strip():
        return ""
    line = address.strip().splitlines()[-1].strip()
    if "," in line:
        return line.split(",")[-1].strip()[:80]
    return line[:80]


def _nested_name(value, field="name") -> str:
    if isinstance(value, dict):
        return str(value.get(field) or "")
    return ""


def _nested_slug(value) -> str:
    if isinstance(value, dict):
        return str(value.get("slug") or "")
    return ""


def _qint(raw: str | None, default: int, lo: int, hi: int) -> int:
    if raw is None or raw == "":
        return default
    try:
        number = int(raw)
    except (TypeError, ValueError):
        raise ApiError(400, "bad_query", "query parameter must be an integer")
    return max(lo, min(hi, number))


def _enum_label(metric: dict, key: str):
    name = str(metric.get("__name__") or "")
    if name.endswith("_info") and key in metric:
        return str(metric.get(key) or "")
    return None


def _iface_id(metric: dict) -> str:
    if metric.get("ifIndex") not in (None, ""):
        return str(metric.get("ifIndex"))
    name = str(metric.get("ifName") or metric.get("ifDescr") or "")
    return name.replace("/", "~")


def _iface_name(metric: dict) -> str:
    return str(metric.get("ifName") or metric.get("ifDescr") or ("if" + str(metric.get("ifIndex") or "")))


def _oper_state(sample: dict):
    metric = sample.get("metric") or {}
    label = _enum_label(metric, "ifOperStatus")
    if label:
        return label
    return _sample_value(sample)


def _admin_state(sample: dict):
    metric = sample.get("metric") or {}
    label = _enum_label(metric, "ifAdminStatus")
    if label:
        return label
    return _sample_value(sample)


def _is_up(state) -> bool:
    return state == "up" or state == 1


def _is_admin_up(state) -> bool:
    return state in ("up", 1, None)


# Input-error counts are over the last 5 minutes (rate(ifInErrors[5m]) * 300).
# 20 errors is a port warning. 50 is a port critical. A warning does not move
# device health; only the critical count does, in explain_health.
ERRORS_WARN_5M = 20.0
ERRORS_CRITICAL_5M = 50.0


def _port_state(oper, admin, errors_5m: float, util: float) -> str:
    if errors_5m >= ERRORS_CRITICAL_5M:
        return "fault"
    if errors_5m >= ERRORS_WARN_5M:
        return "warning"
    if admin in ("down", 2) or oper in ("notPresent", 6):
        return "disabled"
    if _is_up(oper):
        if util >= 85:
            return "warning"
        return "up"
    # Admin enabled with no link is an empty port, not a fault.
    if oper in ("lowerLayerDown", 7, "dormant", 5, "down", 2):
        if _is_admin_up(admin) and admin is not None:
            return "not-connected"
        return "down"
    if oper in ("testing", 3, "unknown", 4):
        return "warning"
    return "down"


def _member_health(ports: list[dict]) -> str:
    states = [p["state"] for p in ports]
    if "fault" in states:
        return "fault"
    if "warning" in states:
        return "warning"
    return "healthy"


def _range_window(range_key: str, custom_min: int) -> tuple[int, int]:
    if range_key == "1h":
        return 3600, 60
    if range_key == "6h":
        return 6 * 3600, 300
    if range_key == "24h":
        return 24 * 3600, 900
    if range_key == "7d":
        return 7 * 86400, 7200
    if range_key == "custom":
        window = max(60, int(custom_min) * 60)
        return window, max(60, int(window / 90))
    raise ApiError(400, "bad_query", "range must be 1h, 6h, 24h, 7d or custom")


def _label_for(ts: float, window_s: int) -> str:
    moment = datetime.fromtimestamp(ts, timezone.utc)
    clock = moment.strftime("%H:%M")
    if window_s >= 6 * 86400:
        return "%s %s" % (_WEEKDAYS[moment.weekday()], clock)
    return clock


def _round(value, places=1):
    if value is None:
        return None
    return round(float(value), places)


class FleetService:
    def __init__(self, settings, client: httpx.Client | None = None, now=None):
        self.settings = settings
        self._client = client
        self._now = now or time.time
        self.cache = _Cache(getattr(settings, "fleet_cache_seconds", 8.0) or 0)

    def _session(self):
        if self._client is not None:
            return nullcontext(self._client)
        verify: bool | str = True
        ca = getattr(self.settings, "ca_file", "") or ""
        if ca and os.path.isfile(ca):
            verify = ca
        return httpx.Client(timeout=httpx.Timeout(30.0, connect=5.0), verify=verify)

    def _send(self, client, method: str, url: str, *, headers=None, params=None, json_body=None, upstream: str):
        try:
            timeout = httpx.Timeout(6.0, connect=2.0) if upstream == "snmp" else None
            response = client.request(method, url, headers=headers, params=params, json=json_body, timeout=timeout)
        except httpx.HTTPError:
            raise UpstreamError(upstream, "%s is not reachable" % _title(upstream))
        return response

    def _json_or_raise(self, response, upstream: str, ok_status=(200,)):
        if response.status_code in ok_status:
            try:
                return response.json()
            except ValueError:
                raise UpstreamError(upstream, "%s returned a response that was not JSON" % _title(upstream))
        if response.status_code in (401, 403):
            raise UpstreamError(upstream, "%s rejected the API token" % _title(upstream))
        raise UpstreamError(upstream, "%s returned HTTP %s" % (_title(upstream), response.status_code))

    # ----- NetBox -----------------------------------------------------------------

    def _headers(self) -> dict:
        headers = netbox_headers(self.settings.netbox_token_file)
        if not headers:
            raise UpstreamError("netbox", "NetBox API token is not configured")
        return headers

    def _walk(self, client, path: str) -> list[dict]:
        headers = self._headers()
        url = self.settings.netbox_url + path
        rows: list[dict] = []
        seen = 0
        while url and seen < _PAGE_CAP:
            if not (url.startswith(self.settings.netbox_url) or url.startswith("/")):
                raise UpstreamError("netbox", "NetBox returned an unexpected page link")
            if url.startswith("/"):
                url = self.settings.netbox_url + url
            response = self._send(client, "GET", url, headers=headers, upstream="netbox")
            body = self._json_or_raise(response, "netbox")
            rows.extend(body.get("results") or [])
            nxt = body.get("next")
            url = nxt if isinstance(nxt, str) and nxt else ""
            seen += 1
        return rows

    def _sites_raw(self, client) -> list[dict]:
        cached = self.cache.get("nb-sites")
        if cached is not None:
            return cached
        rows = []
        for raw in self._walk(client, "/api/dcim/sites/?status=active&limit=1000"):
            region = raw.get("region") if isinstance(raw.get("region"), dict) else {}
            rows.append({
                "id": str(raw.get("id")),
                "name": str(raw.get("name") or ""),
                "slug": str(raw.get("slug") or ""),
                "region": str(region.get("name") or "") or "Unassigned",
                "region_slug": str(region.get("slug") or ""),
                "city": _city(raw),
                "last_updated": str(raw.get("last_updated") or ""),
            })
        self.cache.put("nb-sites", rows, ttl=60)
        return rows

    def _catalog(self, client) -> dict:
        """Role colours and device-type part numbers. Missing either stays blank."""
        cached = self.cache.get("nb-catalog")
        if cached is not None:
            return cached
        colors = {}
        parts = {}
        try:
            for raw in self._walk(client, "/api/dcim/device-roles/?limit=200"):
                colors[str(raw.get("slug") or "")] = str(raw.get("color") or "").strip()
        except UpstreamError:
            log.warning("NetBox device role colours could not be read")
        try:
            for raw in self._walk(client, "/api/dcim/device-types/?limit=1000"):
                parts[str(raw.get("id") or "")] = str(raw.get("part_number") or "").strip()
        except UpstreamError:
            log.warning("NetBox part numbers could not be read")
        payload = {"colors": colors, "parts": parts}
        self.cache.put("nb-catalog", payload, ttl=120)
        return payload

    def _snmp_auth(self, ip: str, role_slug: str) -> str:
        path = getattr(self.settings, "snmp_auth_map", "") or "/opt/insightengine/data/snmp/auth-by-ip.yml"
        try:
            with open(path, "r", encoding="utf-8") as handle:
                for raw in handle:
                    line = raw.split("#", 1)[0].strip()
                    if ":" not in line:
                        continue
                    left, right = line.split(":", 1)
                    if left.strip().strip('"') == ip:
                        name = right.strip().strip('"').strip("'")
                        if name:
                            return name
        except OSError:
            pass
        if role_slug in ("wireless-controller", "wlc"):
            return "ie_wlc_v2"
        if role_slug == "distribution-switch":
            return "ie_snmp_v2"
        return "ntt_snmpv3_auth"

    def _system_facts(self, client, device: dict) -> dict:
        """Uptime, firmware and chassis part number. Prometheus does not scrape these on access switches."""
        ip = str(device.get("ip") or "").split("/")[0].strip()
        role = str(device.get("role_slug") or "")
        if not ip or role in ("access-point", "ap", "wireless-ap", "wireless-ap"):
            return {}
        cached = self.cache.get("system:" + ip)
        if cached is not None:
            return cached
        auth = self._snmp_auth(ip, role)
        base = (getattr(self.settings, "snmp_exporter_url", "") or "http://scrape-lb:9116").rstrip("/")
        try:
            response = self._send(
                client, "GET", base + "/snmp",
                params={"module": "system", "auth": auth, "target": ip},
                upstream="snmp",
            )
        except UpstreamError:
            self.cache.put("system:" + ip, {})
            return {}
        if response.status_code != 200:
            self.cache.put("system:" + ip, {})
            return {}
        facts = parse_system_metrics(response.text or "")
        self.cache.put("system:" + ip, facts)
        return facts

    def _resource_facts(self, client, device: dict) -> dict:
        """CPU and RAM when Prometheus has not scraped those modules yet."""
        ip = str(device.get("ip") or "").split("/")[0].strip()
        role = str(device.get("role_slug") or "")
        if not ip or role in ("access-point", "ap", "wireless-ap"):
            return {}
        cached = self.cache.get("resources:" + ip)
        if cached is not None:
            return cached
        auth = self._snmp_auth(ip, role)
        base = (getattr(self.settings, "snmp_exporter_url", "") or "http://scrape-lb:9116").rstrip("/")
        modules = ["fortinet_health"] if role in ("sdwan", "hub", "core-firewall", "firewall") else ["cisco_pro,cisco_mem"]
        if role not in ("sdwan", "hub", "core-firewall", "firewall"):
            modules.append("fortinet_health")
        text = ""
        for module in modules:
            try:
                response = self._send(
                    client, "GET", base + "/snmp",
                    params={"module": module, "auth": auth, "target": ip},
                    upstream="snmp",
                )
            except UpstreamError:
                continue
            if response.status_code != 200:
                continue
            text += "\n" + (response.text or "")
            parsed = parse_resource_metrics(text)
            if parsed.get("cpu") is not None and parsed.get("mem") is not None:
                break
        facts = parse_resource_metrics(text)
        self.cache.put("resources:" + ip, facts)
        return facts

    def _devices_raw(self, client) -> list[dict]:
        cached = self.cache.get("nb-devices")
        if cached is not None:
            return cached
        sites = {row["id"]: row for row in self._sites_raw(client)}
        catalog = self._catalog(client)
        rows = []
        for raw in self._walk(client, "/api/dcim/devices/?limit=1000"):
            site = raw.get("site") if isinstance(raw.get("site"), dict) else {}
            site_id = str(site.get("id") or "")
            known = sites.get(site_id) or {}
            primary = raw.get("primary_ip4") if isinstance(raw.get("primary_ip4"), dict) else {}
            address = str(primary.get("address") or "").split("/")[0]
            dtype = raw.get("device_type") if isinstance(raw.get("device_type"), dict) else {}
            manufacturer = dtype.get("manufacturer") if isinstance(dtype.get("manufacturer"), dict) else {}
            platform = raw.get("platform") if isinstance(raw.get("platform"), dict) else {}
            role = raw.get("role") if isinstance(raw.get("role"), dict) else {}
            status_raw = raw.get("status")
            if isinstance(status_raw, dict):
                status = str(status_raw.get("value") or status_raw.get("label") or "active")
            else:
                status = str(status_raw or "active")
            rows.append({
                "id": str(raw.get("id")),
                "name": str(raw.get("name") or ("device-%s" % raw.get("id"))),
                "status": status.strip().lower() or "active",
                "role_slug": str(role.get("slug") or ""),
                "role_name": str(role.get("name") or ""),
                "site_id": site_id,
                "site_name": known.get("name") or str(site.get("name") or ""),
                "site_slug": known.get("slug") or str(site.get("slug") or ""),
                "region": known.get("region") or "Unassigned",
                "model": str(dtype.get("model") or ""),
                "slug": str(dtype.get("slug") or ""),
                "part_number": catalog["parts"].get(str(dtype.get("id") or ""), "") or str(dtype.get("part_number") or ""),
                "role_color": catalog["colors"].get(str(role.get("slug") or ""), ""),
                "sw_version": str((raw.get("custom_fields") or {}).get("ie_sw_version") or "") if isinstance(raw.get("custom_fields"), dict) else "",
                "manufacturer": str(manufacturer.get("name") or ""),
                "ip": address,
                "serial": str(raw.get("serial") or ""),
                "platform": str(platform.get("name") or ""),
                "last_updated": str(raw.get("last_updated") or ""),
            })
        self.cache.put("nb-devices", rows, ttl=60)
        return rows

    # ----- Prometheus -------------------------------------------------------------

    def _prom(self, client, query: str) -> list[dict]:
        response = self._send(
            client, "GET", self.settings.prometheus_url + "/api/v1/query",
            params={"query": query}, upstream="prometheus",
        )
        if response.status_code >= 500:
            raise UpstreamError("prometheus", "Prometheus returned HTTP %s" % response.status_code)
        if response.status_code >= 400:
            log.warning("prometheus rejected a query (HTTP %s)", response.status_code)
            return []
        try:
            body = response.json()
        except ValueError:
            raise UpstreamError("prometheus", "Prometheus returned a response that was not JSON")
        if body.get("status") != "success":
            log.warning("prometheus query status was not success")
            return []
        return list((body.get("data") or {}).get("result") or [])

    def _prom_many(self, client, queries: dict[str, str]) -> dict[str, list | None]:
        """Run Prometheus queries together. None means that one query failed."""
        def one(item: tuple[str, str]) -> tuple[str, list | None]:
            key, query = item
            try:
                return key, self._prom(client, query)
            except UpstreamError:
                return key, None

        items = list(queries.items())
        if len(items) <= 1:
            return dict(one(item) for item in items)
        found: dict[str, list | None] = {}
        workers = min(8, len(items))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for key, rows in pool.map(one, items):
                found[key] = rows
        return found

    def _prom_range(self, client, query: str, start: float, end: float, step: int) -> list[dict]:
        response = self._send(
            client, "GET", self.settings.prometheus_url + "/api/v1/query_range",
            params={"query": query, "start": start, "end": end, "step": step},
            upstream="prometheus",
        )
        if response.status_code >= 500:
            raise UpstreamError("prometheus", "Prometheus returned HTTP %s" % response.status_code)
        if response.status_code >= 400:
            log.warning("prometheus rejected a range query (HTTP %s)", response.status_code)
            return []
        try:
            body = response.json()
        except ValueError:
            raise UpstreamError("prometheus", "Prometheus returned a response that was not JSON")
        if body.get("status") != "success":
            return []
        return list((body.get("data") or {}).get("result") or [])

    def _fleet_prom(self, client) -> dict:
        cached = self.cache.get("prom-fleet")
        if cached is not None:
            return cached
        queries = {
            "probe": "max by (hostname, instance) (probe_success)",
            "snmp_up": 'max by (hostname, instance) (up{hostname!=""})',
            "ports_total": "count by (hostname, instance) (ifOperStatus_info) or count by (hostname, instance) (ifOperStatus)",
            "ports_up": 'count by (hostname, instance) (ifOperStatus_info{ifOperStatus="up"}) or count by (hostname, instance) (ifOperStatus == 1)',
            "ports_fault": "count by (hostname, instance) (rate(ifInErrors[5m]) * 300 >= 50)",
            "ports_warn": "count by (hostname, instance) ((rate(ifInErrors[5m]) * 300 >= 20) and (rate(ifInErrors[5m]) * 300 < 50))",
            # sysUpTime is hundredths of a second. FortiGate fgSysUpTime is seconds.
            "uptime": "max by (hostname, instance) (sysUpTime or (fgSysUpTime * 100))",
            "last_poll": (
                "max by (hostname, instance) (timestamp(ifHCInOctets)) "
                'or max by (hostname, instance) (timestamp(up{hostname!=""}))'
            ),
            "cpu": "max by (hostname, instance) (cpmCPUTotal5minRev or fgSysCpuUsage)",
            "memory": "max by (hostname, instance) (ie:device_memory_used_ratio)",
            "temp": "max by (hostname, instance) (ie:device_temperature_celsius)",
            "fan_ok": "min by (hostname, instance) (ie:device_fan_ok)",
            "psu_ok": "min by (hostname, instance) (ie:device_psu_ok)",
        }
        out = {"degraded": False}
        fetched = self._prom_many(client, queries)
        for key in queries:
            index = _index_min if key in ("fan_ok", "psu_ok") else _index_samples
            rows = fetched.get(key)
            if rows is None:
                out["degraded"] = True
                out[key] = ({}, {})
            else:
                out[key] = index(rows)
        self.cache.put("prom-fleet", out, ttl=15)
        return out

    def _selector(self, device: dict) -> str:
        return '{hostname="%s"}' % prom_escape(device["name"])

    # ----- Alertmanager -----------------------------------------------------------

    def _alerts_raw(self, client) -> dict:
        cached = self.cache.get("am-alerts")
        if cached is not None:
            return cached
        try:
            alerts = self._send(client, "GET", self.settings.alertmanager_url + "/api/v2/alerts", upstream="alertmanager")
            silences = self._send(client, "GET", self.settings.alertmanager_url + "/api/v2/silences", upstream="alertmanager")
        except UpstreamError:
            payload = {"degraded": True, "alerts": [], "silences": {}}
            self.cache.put("am-alerts", payload)
            return payload
        if alerts.status_code >= 400 or silences.status_code >= 400:
            payload = {"degraded": True, "alerts": [], "silences": {}}
            self.cache.put("am-alerts", payload)
            return payload
        try:
            alert_rows = alerts.json()
            silence_rows = silences.json()
        except ValueError:
            payload = {"degraded": True, "alerts": [], "silences": {}}
            self.cache.put("am-alerts", payload)
            return payload
        if not isinstance(alert_rows, list):
            alert_rows = []
        silence_map = {}
        if isinstance(silence_rows, list):
            for row in silence_rows:
                if not isinstance(row, dict):
                    continue
                state = ((row.get("status") or {}).get("state")) if isinstance(row.get("status"), dict) else ""
                if state not in ("active", "pending"):
                    continue
                silence_map[str(row.get("id") or "")] = row
        payload = {"degraded": False, "alerts": alert_rows, "silences": silence_map}
        self.cache.put("am-alerts", payload)
        return payload

    # ----- assembly ---------------------------------------------------------------

    def _now_dt(self) -> datetime:
        return datetime.fromtimestamp(self._now(), timezone.utc)

    def _decorated(self, client) -> tuple[list[dict], dict, list[str]]:
        devices = self._devices_raw(client)
        prom = self._fleet_prom(client)
        degraded = ["prometheus"] if prom.get("degraded") else []
        now = self._now()
        built = []
        for device in devices:
            host = device["name"]
            ip = device["ip"]
            probe = _lookup(prom["probe"], host, ip)
            snmp_up = _lookup(prom["snmp_up"], host, ip)
            last_ts = _lookup(prom["last_poll"], host, ip)
            age = None if last_ts is None else max(0.0, now - float(last_ts))
            ports_total = int(_lookup(prom["ports_total"], host, ip) or 0)
            ports_up = int(_lookup(prom["ports_up"], host, ip) or 0)
            ports_fault = int(_lookup(prom["ports_fault"], host, ip) or 0)
            ports_warn = int(_lookup(prom["ports_warn"], host, ip) or 0)
            uptime_text, uptime_s = format_uptime(_lookup(prom["uptime"], host, ip))
            nd_hint = _index_hit(self._netdisco_index(), device.get("ip") or "", device.get("name") or "", self._suffixes())
            classified = classify_device(_netbox_facts(device), nd_hint)
            display, form = classified["role"], classified["form"]
            built.append({
                "id": device["id"],
                "hostname": host,
                "role": display,
                "role_slug": device["role_slug"],
                "site": device["site_name"],
                "siteId": device["site_id"],
                "mgmtIp": ip,
                "modelFamily": device.get("part_number") or device["model"] or device["platform"] or "—",
                "health": "healthy",
                "portsUp": ports_up,
                "portsTotal": ports_total,
                "portsWarn": ports_warn,
                "portsFault": ports_fault,
                "uptime": uptime_text,
                "uptime_s": uptime_s,
                "lastPoll": format_ago(age),
                "last_age": age if age is not None else 10**12,
                "formFactor": form,
                "status": device.get("status") or "active",
                "_device": device,
                "_probe": probe,
                "_snmp": snmp_up,
                "_cpu": _lookup(prom.get("cpu") or ({}, {}), host, ip),
                "_memory": _lookup(prom.get("memory") or ({}, {}), host, ip),
                "_temp": _lookup(prom.get("temp") or ({}, {}), host, ip),
                "_fan_ok": _lookup(prom.get("fan_ok") or ({}, {}), host, ip),
                "_psu_ok": _lookup(prom.get("psu_ok") or ({}, {}), host, ip),
            })
        self._apply_list_health(client, built, degraded)
        roles = sorted({row["role"] for row in built if row["role"]})
        return built, {"degraded": degraded, "roles": roles}, degraded

    def _apply_list_health(self, client, built: list[dict], degraded: list[str]) -> None:
        """Badge for every row from explain_health, including open alerts."""
        alerts = []
        try:
            payload = self._alerts_raw(client)
            if payload.get("degraded") and "alertmanager" not in degraded:
                degraded.append("alertmanager")
            alerts = self._project_alerts(payload, built)
        except Exception:
            log.warning("fleet health could not read alerts")
            if "alertmanager" not in degraded:
                degraded.append("alertmanager")
        by_host: dict[str, list] = {}
        for alert in alerts:
            if alert.get("status") != "open":
                continue
            by_host.setdefault(str(alert.get("deviceHostname") or "").lower(), []).append(alert)
        for row in built:
            explained = explain_health(_row_health_snapshot(row, by_host.get(row["hostname"].lower(), [])))
            row["health"] = explained["health"]
            if explained["health"] == "unreachable":
                row["portsUp"] = 0
                row["uptime"] = "—"

    def _public_row(self, row: dict) -> dict:
        return {
            "id": row["id"],
            "hostname": row["hostname"],
            "role": row["role"],
            "site": row["site"],
            "siteId": row["siteId"],
            "mgmtIp": row["mgmtIp"],
            "modelFamily": row["modelFamily"],
            "health": row["health"],
            "portsUp": row["portsUp"],
            "portsTotal": row["portsTotal"],
            "portsWarn": row["portsWarn"],
            "portsFault": row["portsFault"],
            "uptime": row["uptime"],
                "lastPoll": row["lastPoll"],
                "formFactor": row["formFactor"],
                "status": row.get("status") or "active",
            }

    def _with_degraded(self, body: dict, degraded: list[str]) -> dict:
        if degraded:
            body["degraded"] = degraded
        return body

    def summary(self) -> dict:
        try:
            with self._session() as client:
                rows, _meta, degraded = self._decorated(client)
                alerts = self._alerts_raw(client)
        except UpstreamError as exc:
            raise _as_upstream(exc)
        if alerts.get("degraded") and "alertmanager" not in degraded:
            degraded.append("alertmanager")
        counts = {"healthy": 0, "warning": 0, "critical": 0, "unreachable": 0}
        for row in rows:
            counts[row["health"]] = counts.get(row["health"], 0) + 1
        open_alerts = 0
        for alert in self._project_alerts(alerts, rows):
            if alert["status"] == "open":
                open_alerts += 1
        return self._with_degraded({
            "total": len(rows),
            "healthy": counts["healthy"],
            "warning": counts["warning"],
            "critical": counts["critical"],
            "unreachable": counts["unreachable"],
            "alerts": open_alerts,
            "isExampleData": False,
        }, degraded)

    def list_devices(self, *, page: int, page_size: int, q: str, health: str, role: str, sort: str) -> dict:
        try:
            with self._session() as client:
                rows, meta, degraded = self._decorated(client)
        except UpstreamError as exc:
            raise _as_upstream(exc)
        needle = (q or "").strip().lower()
        if needle:
            rows = [
                row for row in rows
                if needle in row["hostname"].lower() or needle in row["mgmtIp"] or needle in row["site"].lower()
            ]
        if health and health != "all":
            rows = [row for row in rows if row["health"] == health]
        if role and role != "all":
            want = role.strip().lower()
            rows = [row for row in rows if row["role"].lower() == want or row["role_slug"].lower() == want]
        key_name, direction = _parse_sort(sort)
        rows.sort(key=lambda row: _sort_value(row, key_name), reverse=direction == "desc")
        total = len(rows)
        start = (page - 1) * page_size
        page_rows = rows[start:start + page_size]
        return self._with_degraded({
            "rows": [self._public_row(row) for row in page_rows],
            "total": total,
            "isExampleData": False,
            "roles": meta["roles"],
        }, degraded)

    def _netdisco_url(self) -> str:
        return getattr(self.settings, "netdisco_database_url", "") or ""

    def _suffixes(self) -> list[str]:
        return effective_suffixes(self.settings)

    def _netdisco_index(self) -> dict:
        cached = self.cache.get("nd-index")
        if cached is not None:
            return cached
        index = netdisco_index(self._netdisco_url(), self._suffixes())
        self.cache.put("nd-index", index, ttl=60)
        return index

    def _find_device(self, rows: list[dict], device_id: str) -> dict | None:
        return _match_record(rows, device_id, name_key="hostname", ip_key="mgmtIp", suffixes=self._suffixes())

    def get_device(self, device_id: str) -> dict:
        key = unquote(device_id or "").strip()
        cached_detail = self.cache.get("detail:" + key)
        if isinstance(cached_detail, dict):
            return cached_detail
        try:
            with self._session() as client:
                rows, _meta, degraded = self._decorated(client)
                found = self._find_device(rows, key)
                if found is None and not is_form_key(key) and not key.isdigit():
                    ap = self._find_ap(key)
                    if ap is not None:
                        found = self._inventory_for_ap(rows, ap)
                        if found is None:
                            alerts = self._alerts_raw(client)
                            detail = self._detail_from_ap(ap, rows, alerts)
                            return self._with_degraded(detail, degraded)
                if found is None:
                    # Form keys are faceplate samples, not devices. Do not pick a
                    # representative switch or firewall for them.
                    if not is_form_key(key):
                        snap = netdisco_find(self._netdisco_url(), key, self._suffixes())
                        if snap is not None:
                            detail = _detail_from_netdisco(snap, self._now_dt())
                            return self._with_degraded(detail, degraded)
                    raise ApiError(404, "not_found", "unknown device")
                try:
                    detail = self._detail(client, found, rows)
                except Exception:
                    log.warning("device detail assembly failed for %s", found.get("hostname"))
                    detail = _minimal_detail(found, self._now_dt())
                alerts = self._alerts_raw(client)
                self._attach_inventory(client, detail, found, rows)
                self._stamp_observed(client, detail, found)
                if alerts.get("degraded"):
                    for source in detail.get("sources") or []:
                        if source.get("name") == "alertmanager":
                            source["ok"] = False
                            source["detail"] = "Alertmanager is not reachable"
                if detail.pop("_port_degraded", False) and "prometheus" not in degraded:
                    degraded.append("prometheus")
        except UpstreamError as exc:
            raise _as_upstream(exc)
        if alerts.get("degraded") and "alertmanager" not in degraded:
            degraded.append("alertmanager")
        try:
            detail["issues"] = [
                _issue_from_alert(alert, index)
                for index, alert in enumerate(self._project_alerts(alerts, rows))
                if alert["status"] == "open" and alert["deviceHostname"].lower() == found["hostname"].lower()
            ]
        except Exception:
            log.warning("device alerts could not be projected for %s", found.get("hostname"))
            detail["issues"] = []
            if "alertmanager" not in degraded:
                degraded.append("alertmanager")
        detail.setdefault("sources", [])
        self._finish_health(detail, found, alerts, rows)
        for private in ("_snmp_neighbors", "_snmp_at", "_snmp_missing", "_health_inputs", "_ap"):
            detail.pop(private, None)
        body = self._with_degraded(detail, degraded)
        self.cache.put("detail:" + key, body, ttl=15)
        return body

    def _finish_health(self, detail: dict, found: dict, alerts: dict, rows: list[dict]) -> None:
        """Recompute the badge from the same items the Health section lists."""
        inputs = detail.get("_health_inputs") if isinstance(detail.get("_health_inputs"), dict) else {}
        projected = []
        try:
            projected = [
                alert for alert in self._project_alerts(alerts, rows)
                if alert.get("status") == "open" and str(alert.get("deviceHostname") or "").lower() == str(found.get("hostname") or "").lower()
            ]
        except Exception:
            log.warning("device health could not include alerts for %s", found.get("hostname"))
        snap = _row_health_snapshot(found, projected)
        if inputs.get("ports"):
            snap["ports"] = inputs["ports"]
        if inputs.get("cpu") is not None:
            snap["cpu"] = inputs["cpu"]
        if inputs.get("memoryPercent") is not None:
            snap.pop("memoryRatio", None)
            snap["memoryPercent"] = inputs["memoryPercent"]
        if not _basic_switch(found):
            if inputs.get("tempC") is not None:
                snap["tempC"] = inputs["tempC"]
            if inputs.get("fans"):
                snap.pop("fanOk", None)
                snap["fans"] = inputs["fans"]
            if inputs.get("psus"):
                snap.pop("psuOk", None)
                snap["psus"] = inputs["psus"]
        if inputs.get("apStatus"):
            snap["apStatus"] = inputs["apStatus"]
            snap["apName"] = inputs.get("apName") or found.get("hostname") or ""
        if inputs.get("apDown"):
            snap["apDown"] = inputs["apDown"]
        if inputs.get("radios"):
            snap["radios"] = inputs["radios"]
        snap["since"] = inputs.get("since") or snap.get("since") or "—"
        explained = explain_health(snap)
        detail["health"] = explained["health"]
        detail["healthItems"] = explained["items"]
        ap = detail.get("_ap")
        if isinstance(ap, dict):
            panel = detail.get("healthPanel") if isinstance(detail.get("healthPanel"), dict) else {}
            self._merge_ap_panel(panel, ap)
            detail["healthPanel"] = panel
            detail["inNetbox"] = True

    def _inventory_for_ap(self, rows: list[dict], ap: dict) -> dict | None:
        match = match_access_point(rows, ap)
        if match is None:
            return None
        if match.get("hostname") and match.get("_device"):
            return match
        return self._find_device(rows, str(match.get("id") or match.get("name") or ""))

    def _find_ap(self, key: str) -> dict | None:
        text = unquote(key or "").strip()
        if text.lower().startswith("ap:"):
            text = text[3:].strip()
        if not text:
            return None
        low = text.lower()
        wanted_mac = canon_mac(text)
        for row in self._ap_rows():
            values = [str(row.get(field) or "").lower() for field in ("name", "serial", "mac", "ip")]
            same_mac = bool(wanted_mac) and canon_mac(str(row.get("mac") or "")) == wanted_mac
            if low in values or same_mac:
                return row
        return None

    def _ap_rows(self) -> list:
        cached = self.cache.get("ap-snapshot")
        if cached is None:
            try:
                self.list_access_points(page=1, page_size=1, q="", wlc="", site="", status="")
            except Exception:
                return []
            cached = self.cache.get("ap-snapshot") or {}
        return list((cached or {}).get("rows") or [])

    def _ap_panel(self, ap: dict | None) -> dict | None:
        if not ap:
            return None
        return {
            "status": ap.get("status") or "",
            "clients": ap.get("clients"),
            "uptimeSeconds": ap.get("uptimeSeconds"),
            "radios": list(ap.get("radios") or []),
        }

    def _merge_ap_panel(self, panel: dict, ap: dict) -> None:
        block = dict(panel.get("accessPoint") or {})
        block.update({
            "name": ap.get("name") or block.get("name") or "",
            "wlc": ap.get("wlc") or "",
            "model": ap.get("model") or "",
            "serial": ap.get("serial") or "",
            "ip": ap.get("ip") or "",
            "mac": ap.get("mac") or "",
            "location": ap.get("location") or "",
            "ios": ap.get("ios") or "",
            "mode": ap.get("mode") or "",
            "siteTag": ap.get("siteTag") or "",
            "policyTag": ap.get("policyTag") or "",
            "rfTag": ap.get("rfTag") or "",
            "neighborSwitch": ap.get("neighborSwitch") or "",
            "neighborPort": ap.get("neighborPort") or "",
            "clients": ap.get("clients") if ap.get("clients") is not None else block.get("clients"),
            "status": ap.get("status") or block.get("status") or "",
            "radios": ap.get("radios") or block.get("radios") or [],
            "ssids": ap.get("ssids") or [],
            "uptimeSeconds": ap.get("uptimeSeconds") if ap.get("uptimeSeconds") is not None else block.get("uptimeSeconds"),
        })
        if not block.get("note"):
            block["note"] = "Status, radios and clients come from the wireless controller."
        panel["accessPoint"] = block

    def _detail_from_ap(self, ap: dict, rows: list[dict], alerts: dict) -> dict:
        name = str(ap.get("name") or "access-point")
        projected = []
        try:
            projected = [
                alert for alert in self._project_alerts(alerts, rows)
                if alert.get("status") == "open" and str(alert.get("deviceHostname") or "").lower() == name.lower()
            ]
        except Exception:
            projected = []
        explained = explain_health({
            "since": "—",
            "apStatus": ap.get("status") or "",
            "apName": name,
            "radios": ap.get("radios") or [],
            "alerts": [_alert_health(alert) for alert in projected],
        })
        panel = build_health_panel("ap", ap=self._ap_panel(ap))
        self._merge_ap_panel(panel, ap)
        neighbors = []
        if ap.get("neighborSwitch"):
            neighbors.append({
                "localPort": "uplink",
                "remoteName": ap.get("neighborSwitch") or "",
                "remotePort": ap.get("neighborPort") or "",
                "remoteAddress": "",
                "protocol": "cdp",
                "source": "wlc",
            })
        face = _faceplate("ceiling-ap", "Access point", name, ap.get("model") or "", [])
        face["apState"] = "down" if str(ap.get("status") or "").lower() == "down" else "up"
        seconds = ap.get("uptimeSeconds")
        uptime = "—"
        if isinstance(seconds, (int, float)) and seconds >= 0:
            uptime, _ignored = format_uptime(float(seconds) * 100)
        return {
            "id": "ap:%s" % name,
            "hostname": name,
            "role": "Access point",
            "site": ap.get("suggestedSite") or ap.get("netboxSite") or ap.get("site") or "—",
            "siteId": "",
            "mgmtIp": ap.get("ip") or "—",
            "modelFamily": ap.get("model") or "Access point",
            "health": explained["health"],
            "healthItems": explained["items"],
            "status": ap.get("status") or "active",
            "inNetbox": False,
            "uptime": uptime,
            "lastPoll": "—",
            "firmware": ap.get("ios") or "—",
            "serialMasked": display_serial(ap.get("serial") or ""),
            "faceplate": face,
            "issues": [_issue_from_alert(alert, index) for index, alert in enumerate(projected)],
            "checks": [],
            "hardware": [],
            "healthPanel": panel,
            "checkRunAt": _clock_stamp(self._now_dt()),
            "neighbors": neighbors,
            "neighborNote": "",
            "interfaces": [],
            "addresses": [],
            "history": [],
            "sources": [
                {"name": "netbox", "ok": False, "detail": "Not in NetBox"},
                {"name": "prometheus", "ok": True, "detail": "Wireless controller telemetry"},
                {"name": "alertmanager", "ok": not bool(alerts.get("degraded")), "detail": ""},
            ],
        }

    def approve_access_points(self, body: dict) -> dict:
        """Create NetBox devices for wireless APs. Ones already present are skipped."""
        if not isinstance(body, dict):
            raise ApiError(400, "bad_body", "body must be a JSON object")
        points = body.get("accessPoints")
        if not isinstance(points, list) or not points or len(points) > 100:
            raise ApiError(400, "bad_body", "accessPoints must be 1 to 100 access points")
        role = str(body.get("role") or "access-point").strip() or "access-point"
        site = str(body.get("site") or "").strip()
        if not site:
            raise ApiError(400, "bad_body", "site is required")
        platform = str(body.get("platform") or "").strip()
        headers = netbox_headers(self.settings.netbox_token_file)
        if not headers:
            raise ApiError(503, "netbox_token", "NetBox API token is not configured")
        try:
            with self._session() as client:
                devices = self._devices_raw(client)
        except UpstreamError as exc:
            raise _as_upstream(exc)
        known = self._ap_rows()
        writer = NetBoxWriter(self.settings.netbox_url, headers)
        results = []
        created_any = False
        for raw in points:
            if not isinstance(raw, dict) or not str(raw.get("name") or "").strip():
                results.append({"name": "", "wlc": "", "status": "failed", "reason": "access point name is required", "deviceId": ""})
                continue
            ap = _posted_ap(raw, known)
            chosen_site = str(raw.get("site") or site).strip() or site
            match = match_access_point(devices, ap)
            if match is not None:
                results.append({
                    "name": ap["name"],
                    "wlc": ap.get("wlc") or "",
                    "status": "skipped",
                    "reason": "Already in NetBox",
                    "deviceId": str(match.get("id") or ""),
                })
                continue
            try:
                made = writer.approve_access_point(ap, role=role, site=chosen_site, platform=platform)
            except Exception:
                log.warning("access point approve failed for %s", ap.get("name"))
                results.append({
                    "name": ap["name"],
                    "wlc": ap.get("wlc") or "",
                    "status": "failed",
                    "reason": "NetBox did not accept the access point",
                    "deviceId": "",
                })
                continue
            created_any = True
            device_id = str(made.get("device_id") or "")
            devices.append({"id": device_id, "name": ap["name"], "serial": ap.get("serial") or "", "site_name": chosen_site})
            results.append({
                "name": ap["name"],
                "wlc": ap.get("wlc") or "",
                "status": "created",
                "reason": "",
                "deviceId": device_id,
            })
        if created_any:
            self.cache.drop("nb-devices")
            self.cache.drop("ap-snapshot")
            self.cache.drop_prefix("detail:")
        return {"ok": all(row["status"] != "failed" for row in results), "results": results}

    def sync_netbox_inventory(self, device_id: str) -> dict:
        """Write the live model, serial number and firmware onto the NetBox device."""
        key = unquote(device_id or "").strip()
        if not key or is_form_key(key):
            raise ApiError(404, "not_found", "unknown device")
        headers = netbox_headers(self.settings.netbox_token_file)
        if not headers:
            raise ApiError(503, "netbox_token", "NetBox API token is not configured")
        try:
            with self._session() as client:
                rows, _meta, _degraded = self._decorated(client)
                found = self._find_device(rows, key)
                if found is None:
                    raise ApiError(404, "not_found", "unknown device")
                device = found.get("_device") or {}
                nb_id = str(device.get("id") or "")
                if not nb_id.isdigit():
                    raise ApiError(400, "not_in_netbox", "This device is not in NetBox")
                nd = _index_hit(self._netdisco_index(), device.get("ip") or "", device.get("name") or "", self._suffixes()) or {}
                ap = None
                if str(device.get("role_slug") or "") in ("access-point", "ap", "wireless-ap"):
                    ap = self._find_ap(str(device.get("name") or ""))
                facts = self._system_facts(client, device)
                live = live_inventory(facts, nd, ap)
                names = live_model_names(facts, nd, ap)
                hostname = str(device.get("name") or found.get("hostname") or nb_id)
        except UpstreamError as exc:
            raise _as_upstream(exc)
        if not live["model"] and not live["serial"] and not live["firmware"]:
            return {
                "ok": True,
                "updated": [],
                "note": "SNMP and Netdisco did not report a model, serial number or firmware.",
                "hostname": hostname,
            }
        writer = NetBoxWriter(self.settings.netbox_url, headers)
        note = ""
        body: dict = {}
        updated: list[str] = []
        try:
            current = writer._req("GET", "/api/dcim/devices/%s/" % nb_id)
            if not isinstance(current, dict):
                raise ApiError(502, "netbox_error", "NetBox did not return this device")
            dtype = current.get("device_type") if isinstance(current.get("device_type"), dict) else {}
            manufacturer = dtype.get("manufacturer") if isinstance(dtype, dict) else None
            if isinstance(manufacturer, dict):
                manufacturer_id = manufacturer.get("id")
            elif isinstance(manufacturer, int):
                manufacturer_id = manufacturer
            else:
                manufacturer_id = None
            matched, note = _pick_device_type(writer, manufacturer_id, names, dtype if isinstance(dtype, dict) else {})
            body, updated = inventory_patch(current, live, matched)
            if "firmware" in updated:
                writer._ensure_text_field("ie_sw_version", "Software version")
            if body:
                writer._req("PATCH", "/api/dcim/devices/%s/" % nb_id, body)
        except ApiError:
            raise
        except RuntimeError as exc:
            if "-> 404" in str(exc):
                raise ApiError(404, "not_found", "This device is not in NetBox")
            log.warning("netbox inventory sync failed for %s", hostname)
            raise ApiError(502, "netbox_error", "NetBox did not accept the model, serial number or firmware")
        except Exception:
            log.warning("netbox inventory sync failed for %s", hostname)
            raise ApiError(502, "netbox_error", "NetBox did not accept the model, serial number or firmware")
        if body:
            self.cache.drop("nb-devices")
            self.cache.drop_prefix("detail:")
        if not body and not note:
            note = "NetBox already has this model, serial number and firmware."
        return {"ok": True, "updated": updated, "note": note, "hostname": hostname}

    def device_access(self, device_id: str) -> dict:
        """Hostname, management IP and platform. Used by the read-only CLI."""
        key = unquote(device_id or "").strip()
        try:
            with self._session() as client:
                rows = self._devices_raw(client)
        except UpstreamError as exc:
            raise _as_upstream(exc)
        found = _match_record(rows, key, name_key="name", ip_key="ip")
        if found is None and not is_form_key(key):
            snap = netdisco_find(self._netdisco_url(), key, self._suffixes())
            device = (snap or {}).get("device") if snap else None
            if device:
                hostname = device.get("dns") or device.get("name") or device.get("ip") or ""
                return {
                    "id": device.get("ip") or hostname,
                    "hostname": hostname,
                    "ip": device.get("ip") or "",
                    "platform": device.get("os") or "",
                    "manufacturer": device.get("vendor") or "",
                }
        if found is None:
            raise ApiError(404, "not_found", "unknown device")
        return {
            "id": found["id"],
            "hostname": found["name"],
            "ip": found["ip"],
            "platform": found["platform"],
            "manufacturer": found["manufacturer"],
        }

    def _stamp_observed(self, client, detail: dict, found: dict) -> None:
        """Live model, serial and firmware the NetBox sync button writes."""
        comparison = detail.get("comparison")
        if not isinstance(comparison, dict):
            return
        device = found.get("_device") or {}
        nd = comparison.get("netdisco") if isinstance(comparison.get("netdisco"), dict) else {}
        ap = detail.get("_ap") if isinstance(detail.get("_ap"), dict) else None
        try:
            facts = self._system_facts(client, device) if device else {}
        except Exception:
            facts = {}
        comparison["observed"] = live_inventory(facts, nd, ap)

    def _attach_inventory(self, client, detail: dict, found: dict, rows: list[dict]) -> None:
        """NetBox interfaces and IPs, Prometheus history, Oxidized and Netdisco.

        A missing source is recorded on the device and does not fail the page.
        Interface pages past the first 200 are followed until NetBox reports no next link.
        """
        device = found.get("_device") or {}
        device_id = str(device.get("id") or found.get("id") or "")
        interfaces, iface_error = self._netbox_rows(
            client, "/api/dcim/interfaces/?device_id=%s&limit=200" % quote(device_id, safe="")
        )
        addresses, addr_error = self._netbox_rows(
            client, "/api/ipam/ip-addresses/?device_id=%s&limit=200" % quote(device_id, safe="")
        )
        detail["interfaces"] = [
            _public_interface(row) for row in interfaces
            if isinstance(row, dict) and _is_cable_port(row)
        ]
        panel = detail.get("healthPanel")
        if isinstance(panel, dict) and panel.get("interfacesSupported"):
            marked = critical_names_from_interfaces(detail["interfaces"])
            for item in panel.get("interfaces") or []:
                name = str(item.get("name") or "").lower()
                if name in marked:
                    item["criticalPath"] = True
        detail["addresses"] = [_public_address(row) for row in addresses if isinstance(row, dict)]
        selector = self._selector(device) if device else ""
        history = []
        history_error = ""
        if selector:
            try:
                history = self._throughput(client, selector, self._now() - 3600, self._now(), 60, 3600)
            except UpstreamError:
                history_error = "Prometheus history is not available"
            except Exception:
                history_error = "Prometheus history is not available"
        detail["history"] = history
        backup = self._oxidized_backup(client, found.get("hostname") or "")
        detail["backup"] = backup
        snap = netdisco_snapshot(
            self._netdisco_url(),
            ip=device.get("ip") or found.get("mgmtIp") or "",
            name=device.get("name") or found.get("hostname") or "",
            suffixes=self._suffixes(),
        )
        snmp_neighbors = list(detail.get("_snmp_neighbors") or [])
        detail["neighbors"] = merge_neighbors(snap.get("neighbors") or [], snmp_neighbors)
        if snap.get("available") and not snap.get("device"):
            detail["neighborNote"] = snap.get("reason") or "Netdisco has not discovered this device yet"
        else:
            detail["neighborNote"] = ""
        self._apply_faceplate(detail, found, interfaces, snap, rows)
        detail["sources"] = [
            {"name": "netbox", "ok": not iface_error and not addr_error, "detail": iface_error or addr_error},
            {"name": "prometheus", "ok": not detail.get("_port_degraded") and not history_error, "detail": history_error},
            {"name": "alertmanager", "ok": True, "detail": ""},
            {"name": "oxidized", "ok": bool(backup.get("available")), "detail": backup.get("reason") or ""},
            {"name": "netdisco", "ok": bool(snap.get("available")), "detail": snap.get("reason") or ""},
        ]

    def _apply_faceplate(self, detail: dict, found: dict, interfaces: list, snap: dict, rows: list[dict]) -> None:
        """Rebuild the faceplate from NetBox and Netdisco, keeping Prometheus oper state."""
        device = found.get("_device") or {}
        prom_ports = _ports_from_faceplate(detail.get("faceplate") or {})
        nd_device = snap.get("device") if isinstance(snap.get("device"), dict) else None
        nd_payload = None
        if nd_device or snap.get("ports"):
            nd_payload = dict(nd_device or {})
            nd_payload["ports"] = snap.get("ports") or []
        facts = _netbox_facts(device)
        facts["interfaces"] = [row for row in interfaces if isinstance(row, dict)]
        classified = classify_device(facts, nd_payload)
        source = classified["faceplate_source"]
        ports = list(classified["ports"])
        if source == "none":
            ports = [_present_port(port) for port in prom_ports]
            source = "prometheus" if prom_ports else "none"
        else:
            ports = _overlay_port_state(ports, prom_ports)
        _annotate_interfaces(detail.get("interfaces") or [], prom_ports)
        ports = _overlay_neighbours(ports, snap.get("ports") or [], rows, detail.get("_snmp_neighbors") or [], self._suffixes())
        form = classified["form"] if classified["form"] in FORM_FACTORS else "generic"
        role = classified["role"]
        detail["role"] = role
        detail["status"] = found.get("status") or device.get("status") or "active"
        shown_model = (device.get("part_number") or "").strip() or device.get("model") or (nd_device or {}).get("model") or ""
        face = _faceplate(
            form, role, detail.get("hostname") or "",
            shown_model,
            ports,
            {
                "model": shown_model,
                "part_number": device.get("part_number") or "",
                "slug": device.get("slug") or "",
                "manufacturer": device.get("manufacturer") or "",
            },
        )
        self._paint_ap_face(face, detail.get("hostname") or "")
        face["snmpAt"] = detail.get("_snmp_at") or ""
        if "_snmp_missing" in detail:
            face["snmpMissing"] = bool(detail.get("_snmp_missing"))
        else:
            face["snmpMissing"] = not bool(prom_ports)
        detail["faceplate"] = face
        comparison = dict(classified["comparison"])
        comparison["faceplateSource"] = source
        detail["comparison"] = comparison
        if device.get("model"):
            detail["modelFamily"] = device["model"]

    def _netbox_rows(self, client, path: str):
        try:
            return self._walk(client, path), ""
        except UpstreamError as exc:
            return [], exc.message

    def _oxidized_backup(self, client, name: str) -> dict:
        cached = self.cache.get("oxidized:" + (name or ""))
        if isinstance(cached, dict):
            return cached
        empty = {"available": False, "reason": "", "status": "", "at": "", "config": ""}

        def remember(body: dict) -> dict:
            self.cache.put("oxidized:" + (name or ""), body, ttl=60)
            return body

        safe_name = quote(str(name or ""), safe="")
        if not safe_name:
            empty["reason"] = "This device has no name for Oxidized"
            return remember(empty)
        base = (getattr(self.settings, "oxidized_url", "") or "http://oxidized:8888").rstrip("/")
        try:
            shown = self._send(client, "GET", "%s/node/show/%s.json" % (base, safe_name), upstream="oxidized")
        except UpstreamError:
            empty["reason"] = "Oxidized is not reachable"
            return remember(empty)
        if shown.status_code == 404:
            empty["reason"] = "Oxidized has no backup for this device"
            return remember(empty)
        if shown.status_code >= 400:
            empty["reason"] = "Oxidized returned HTTP %s" % shown.status_code
            return remember(empty)
        status = ""
        at = ""
        try:
            body = shown.json()
        except ValueError:
            body = {}
        if isinstance(body, dict):
            last = body.get("last") if isinstance(body.get("last"), dict) else {}
            status = str(last.get("status") or "")
            at = str(last.get("end") or last.get("start") or "")
        config = ""
        try:
            fetched = self._send(client, "GET", "%s/node/fetch/%s" % (base, safe_name), upstream="oxidized")
            if fetched.status_code < 400:
                config = redact_config(fetched.text or "")
        except UpstreamError:
            pass
        return remember({"available": True, "reason": "", "status": status, "at": at, "config": config})

    def _detail(self, client, row: dict, rows: list[dict]) -> dict:
        device = row["_device"]
        selector = self._selector(device)
        cached = self.cache.get("ports:" + device["name"])
        if cached is None:
            try:
                cached = self._load_ports(client, selector, device.get("name") or "")
            except UpstreamError:
                cached = {"degraded": True, "ports": [], "cpu": None, "mem": None, "temp": None, "fans": [], "psus": [], "rtt": None}
            self.cache.put("ports:" + device["name"], cached)
        if cached.get("cpu") is None or cached.get("mem") is None:
            extra = self._resource_facts(client, device)
            if cached.get("cpu") is None and extra.get("cpu") is not None:
                cached["cpu"] = extra["cpu"]
            if cached.get("mem") is None and extra.get("mem") is not None:
                cached["mem"] = extra["mem"]
        ports = cached["ports"]
        form = row["formFactor"]
        faceplate = _faceplate(
            form, row["role"], row["hostname"], device.get("model") or "", ports,
            {
                "model": device.get("model") or "",
                "part_number": device.get("part_number") or "",
                "slug": device.get("slug") or "",
                "manufacturer": device.get("manufacturer") or "",
            },
        )
        checks, hardware = _checks_and_hardware(row, cached, self._now_dt())
        device = row["_device"]
        profile = classify_profile(
            row.get("role_slug") or row.get("role") or "",
            device.get("platform") or "",
            device.get("manufacturer") or "",
            device.get("model") or "",
        )
        mem = cached.get("mem")
        fan_states = [_env_state(sample, "ciscoEnvMonFanState") or _env_state(sample, "cefcFanTrayOperStatus") for sample in cached.get("fans") or []]
        psu_states = [_env_state(sample, "ciscoEnvMonSupplyState") or _env_state(sample, "cefcFRUPowerOperStatus") for sample in cached.get("psus") or []]
        psu_states.extend(aireos_psu_states(cached.get("aireos_psu") or []))
        fan_clean = [item for item in fan_states if item]
        psu_clean = [item for item in psu_states if item]
        ap_row = self._find_ap(row["hostname"]) if profile == "ap" else None
        health_panel = build_health_panel(
            profile,
            cpu=None if cached.get("cpu") is None else float(cached["cpu"]),
            memory_ratio=None if mem is None else float(mem) / 100.0,
            memory_detail="Used percent",
            fan_states=fan_clean,
            psu_states=psu_clean,
            temp_c=cached.get("temp"),
            ports=cached.get("ports") or [],
            wlc_joined=cached.get("joined_aps"),
            wlc_clients=cached.get("wlc_clients"),
            ap=self._ap_panel(ap_row) if ap_row else (self._ap_for_device(client, row["hostname"]) if profile == "ap" else None),
        )
        if ap_row:
            self._merge_ap_panel(health_panel, ap_row)
        down_aps = None
        if profile in ("aireos", "iosxe-wlc"):
            try:
                counted = self._prom(
                    client,
                    'count(ie_wlc_ap_oper_up{wlc="%s"} == 0)' % prom_escape(row["hostname"]),
                )
                down_aps = _first_value(counted)
            except UpstreamError:
                down_aps = None
        self._paint_ap_face(faceplate, row["hostname"])
        facts = self._system_facts(client, device)
        part = (device.get("part_number") or "").strip() or (facts.get("part") or "")
        firmware = (facts.get("firmware") or "").strip() or str(device.get("sw_version") or "").strip().rstrip("$") or (device.get("platform") or "")
        serial = str(device.get("serial") or "").strip() or str(facts.get("serial") or "").strip()
        uptime = row["uptime"]
        if (not uptime or uptime == "—") and facts.get("uptime") is not None:
            uptime, _seconds = format_uptime(facts["uptime"])
        if part:
            faceplate["partNumber"] = part
        detail = {
            "id": row["id"],
            "hostname": row["hostname"],
            "role": row["role"],
            "roleColor": device.get("role_color") or "",
            "reachable": row.get("_probe") == 1,
            "site": row["site"],
            "siteId": row["siteId"],
            "mgmtIp": row["mgmtIp"] or "—",
            "modelFamily": part or row["modelFamily"],
            "partNumber": part,
            "health": row["health"],
            "status": row.get("status") or "active",
            "uptime": uptime,
            "lastPoll": row["lastPoll"],
            "firmware": firmware or "—",
            "serialMasked": display_serial(serial),
            "faceplate": faceplate,
            "issues": [],
            "checks": checks,
            "hardware": hardware,
            "healthPanel": health_panel,
            "checkRunAt": _clock_stamp(self._now_dt()),
            "_port_degraded": bool(cached.get("degraded")),
            "_snmp_at": cached.get("snmp_at") or "",
            "_snmp_missing": not bool(cached.get("has_if_mib")),
            "_snmp_neighbors": cached.get("neighbors") or [],
            "_health_inputs": {
                "ports": cached.get("ports") or [],
                "cpu": cached.get("cpu"),
                "memoryPercent": cached.get("mem"),
                "tempC": cached.get("temp"),
                "fans": fan_clean,
                "psus": psu_clean,
                "since": row.get("lastPoll") or "—",
                "apStatus": (ap_row or {}).get("status") if ap_row else "",
                "apName": row["hostname"],
                "apDown": down_aps,
                "radios": (ap_row or {}).get("radios") or [],
            },
            "_ap": ap_row,
        }
        return detail

    def _load_ports(self, client, selector: str, hostname: str = "") -> dict:
        host_name = hostname or ""
        safe_host = prom_escape(host_name)
        queries = {
            "oper": "ifOperStatus_info%s or ifOperStatus%s" % (selector, selector),
            "admin": "ifAdminStatus_info%s or ifAdminStatus%s" % (selector, selector),
            "speed": "ifHighSpeed%s" % selector,
            "inbound": "rate(ifHCInOctets%s[5m])" % selector,
            "outbound": "rate(ifHCOutOctets%s[5m])" % selector,
            "errors": "rate(ifInErrors%s[5m])" % selector,
            "discards_in": "rate(ifInDiscards%s[5m])" % selector,
            "discards_out": "rate(ifOutDiscards%s[5m])" % selector,
            "cpu": "avg(cpmCPUTotal5minRev%s) or avg(fgSysCpuUsage%s)" % (selector, selector),
            "mem": (
                "(sum(ciscoMemoryPoolUsed%(s)s) / clamp_min(sum(ciscoMemoryPoolUsed%(s)s) + sum(ciscoMemoryPoolFree%(s)s), 1)) * 100 "
                "or avg(fgSysMemUsage%(s)s)"
            ) % {"s": selector},
            "temp": "max(ciscoEnvMonTemperatureStatusValue%s)" % selector,
            "fans": "ciscoEnvMonFanState_info%s or ciscoEnvMonFanState%s" % (selector, selector),
            "psus": "ciscoEnvMonSupplyState_info%s or ciscoEnvMonSupplyState%s" % (selector, selector),
            "rtt": "avg(probe_duration_seconds%s)" % selector,
            "joined_aps": (
                'max(cLApGlobalAPConnectCount%s) or count(ie_wlc_ap_admin_status{wlc="%s"}) or count(ie_wlc_ap_oper_status{wlc="%s"})'
                % (selector, safe_host, safe_host)
            ),
            "wlc_clients": (
                'max(bsnGlobalDot11SystemMobileStations%s) or sum(ie_wlc_ap_clients{wlc="%s"}) or sum(ie_wlc_radio_clients{wlc="%s"})'
                % (selector, safe_host, safe_host)
            ),
            "aireos_psu": (
                "agentSwitchInfoPowerSupply1Present%s or agentSwitchInfoPowerSupply1Operational%s or "
                "agentSwitchInfoPowerSupply2Present%s or agentSwitchInfoPowerSupply2Operational%s"
                % (selector, selector, selector, selector)
            ),
        }
        for metric in (
            "cdpCacheDeviceId", "cdpCacheDevicePort", "cdpCacheAddress", "cdpCachePlatform",
            "lldpRemSysName", "lldpRemPortId", "lldpRemPortDesc", "lldpRemManAddrIfId", "lldpLocPortId",
        ):
            queries[metric] = "%s%s or %s_info%s" % (metric, selector, metric, selector)
        fetched = self._prom_many(client, queries)
        if fetched.get("oper") is None:
            raise UpstreamError("prometheus", "Prometheus is not reachable")

        def rows(key: str) -> list:
            found = fetched.get(key)
            return found if isinstance(found, list) else []

        oper, admin, speed = rows("oper"), rows("admin"), rows("speed")
        ports = _join_ports(oper, admin, speed, rows("inbound"), rows("outbound"), rows("errors"), rows("discards_in"), rows("discards_out"))
        suffixes = self._suffixes()
        cdp = neighbors_from_cdp(
            rows("cdpCacheDeviceId"), rows("cdpCacheDevicePort"),
            rows("cdpCacheAddress"), rows("cdpCachePlatform"),
            ports, suffixes,
        )
        lldp = neighbors_from_lldp(
            rows("lldpRemSysName"), rows("lldpRemPortId"), rows("lldpRemPortDesc"),
            rows("lldpRemManAddrIfId"), rows("lldpLocPortId"),
            ports, suffixes,
        )
        return {
            "degraded": False,
            "ports": ports,
            "neighbors": merge_neighbors(cdp, lldp),
            "snmp_at": _latest_stamp(oper or admin or speed),
            "has_if_mib": bool(oper or admin),
            "cpu": _first_value(rows("cpu")),
            "mem": _first_value(rows("mem")),
            "temp": _first_value(rows("temp")),
            "fans": rows("fans"),
            "psus": rows("psus"),
            "rtt": _first_value(rows("rtt")),
            "joined_aps": _first_value(rows("joined_aps")),
            "wlc_clients": _first_value(rows("wlc_clients")),
            "aireos_psu": rows("aireos_psu"),
        }

    def list_sites(self, *, page: int, page_size: int, q: str, health: str, region: str) -> dict:
        try:
            with self._session() as client:
                devices, _meta, degraded = self._decorated(client)
                sites = self._sites_raw(client)
                alerts = self._alerts_raw(client)
        except UpstreamError as exc:
            raise _as_upstream(exc)
        if alerts.get("degraded") and "alertmanager" not in degraded:
            degraded.append("alertmanager")
        projected = self._project_alerts(alerts, devices)
        by_site: dict[str, list[dict]] = {}
        for row in devices:
            by_site.setdefault(row["siteId"], []).append(row)
        built = []
        for site in sites:
            members = by_site.get(site["id"], [])
            site_health = worst_health([row["health"] for row in members])
            open_count = 0
            for alert in projected:
                if alert["status"] != "open":
                    continue
                if alert["siteId"] == site["id"] or alert["site"].lower() == site["name"].lower():
                    open_count += 1
            updated = _parse_time(site.get("last_updated") or "")
            last = "—"
            if updated is not None:
                last = format_ago((self._now_dt() - updated).total_seconds())
            built.append({
                "id": site["id"],
                "name": site["name"],
                "region": site["region"],
                "region_slug": site.get("region_slug") or "",
                "city": site["city"],
                "deviceCount": len(members),
                "health": site_health,
                "alerts": open_count,
                "lastDiscovery": last,
            })
        needle = (q or "").strip().lower()
        if needle:
            built = [
                row for row in built
                if needle in row["name"].lower() or needle in row["city"].lower() or needle in row["region"].lower()
            ]
        built.sort(key=lambda row: row["name"].lower())
        if health and health != "all":
            built = [row for row in built if row["health"] == health]
        if region and region != "all":
            want = region.strip().lower()
            built = [row for row in built if row["region"].lower() == want or row["region_slug"].lower() == want]
        regions = sorted({row["region"] for row in built} | {site["region"] for site in sites if site.get("region")})
        total = len(built)
        start = (page - 1) * page_size
        page_rows = []
        for row in built[start:start + page_size]:
            page_rows.append({
                "id": row["id"], "name": row["name"], "region": row["region"], "city": row["city"],
                "deviceCount": row["deviceCount"], "health": row["health"], "alerts": row["alerts"],
                "lastDiscovery": row["lastDiscovery"],
            })
        return self._with_degraded({
            "rows": page_rows,
            "total": total,
            "isExampleData": False,
            "regions": regions,
        }, degraded)

    def site_devices(self, site_id: str) -> list[dict]:
        key = unquote(site_id or "").strip()
        if key.startswith("site-"):
            rest = key[5:]
            key = str(int(rest)) if rest.isdigit() else rest
        try:
            with self._session() as client:
                devices, _meta, _degraded = self._decorated(client)
                sites = self._sites_raw(client)
        except UpstreamError as exc:
            raise _as_upstream(exc)
        match = None
        for site in sites:
            if site["id"] == key or site["slug"] == key or site["name"].lower() == key.lower():
                match = site
                break
        if match is None and key.isdigit():
            # tolerate a numeric NetBox id that was not in the active list
            match = {"id": key}
        if match is None:
            return []
        rows = [self._public_row(row) for row in devices if row["siteId"] == match["id"]]
        rows.sort(key=lambda row: row["hostname"].lower())
        return rows

    def _project_alerts(self, payload: dict, devices: list[dict]) -> list[dict]:
        by_host = {row["hostname"].lower(): row for row in devices}
        silences = payload.get("silences") or {}
        now = self._now_dt()
        projected = []
        for raw in payload.get("alerts") or []:
            if not isinstance(raw, dict):
                continue
            labels = raw.get("labels") or {}
            annotations = raw.get("annotations") or {}
            if not isinstance(labels, dict):
                labels = {}
            if not isinstance(annotations, dict):
                annotations = {}
            status = raw.get("status") if isinstance(raw.get("status"), dict) else {}
            silenced = [str(item) for item in (status.get("silencedBy") or []) if item]
            host = str(labels.get("hostname") or labels.get("device") or "")
            device = by_host.get(host.lower())
            site_name = str(labels.get("site") or (device["site"] if device else ""))
            starts = _parse_time(str(raw.get("startsAt") or "")) or now
            age = max(0, int((now - starts).total_seconds() // 60))
            ack_by = ""
            ack_at = ""
            if silenced:
                silence = silences.get(silenced[0]) or {}
                ack_by = str(silence.get("createdBy") or "")
                ack_moment = _parse_time(str(silence.get("startsAt") or ""))
                if ack_moment is not None:
                    ack_at = _stamp(ack_moment)
            severity = _severity(str(labels.get("severity") or ""))
            item = {
                "id": str(raw.get("fingerprint") or labels.get("alertname") or ""),
                "severity": severity,
                "title": str(annotations.get("summary") or labels.get("alertname") or "Alert"),
                "detail": str(annotations.get("description") or ""),
                "site": site_name,
                "siteId": device["siteId"] if device else "",
                "deviceHostname": host,
                "deviceId": device["id"] if device else "",
                "formFactor": device["formFactor"] if device else "generic",
                "category": str(labels.get("whatisdown") or labels.get("category") or labels.get("alertname") or "Alert"),
                "raisedAt": _stamp(starts),
                "ageMinutes": age,
                "status": "acknowledged" if silenced else "open",
                "_labels": labels,
                "_raw": raw,
            }
            if ack_by:
                item["acknowledgedBy"] = ack_by
            if ack_at:
                item["acknowledgedAt"] = ack_at
            projected.append(item)
        projected.sort(key=lambda item: (item["ageMinutes"], item["id"]))
        return projected[:_ALERT_CAP]

    def list_alerts(self, *, status: str, severity: str, site: str) -> list[dict]:
        try:
            with self._session() as client:
                payload = self._alerts_raw(client)
                if payload.get("degraded"):
                    raise UpstreamError("alertmanager", "Alertmanager is not reachable")
                try:
                    devices, _meta, _degraded = self._decorated(client)
                except UpstreamError as exc:
                    if exc.upstream == "netbox":
                        devices = []
                    else:
                        raise
        except UpstreamError as exc:
            raise _as_upstream(exc)
        rows = self._project_alerts(payload, devices)
        if status and status != "all":
            rows = [row for row in rows if row["status"] == status]
        if severity and severity != "all":
            rows = [row for row in rows if row["severity"] == severity]
        if site and site != "all":
            want = site.strip().lower()
            rows = [row for row in rows if row["site"].lower() == want or row["siteId"].lower() == want]
        public = []
        for row in rows:
            item = {key: value for key, value in row.items() if not key.startswith("_")}
            public.append(item)
        return public

    def acknowledge(self, ids, created_by: str) -> dict:
        if not isinstance(ids, list) or not ids or not all(isinstance(item, str) and item.strip() for item in ids):
            raise ApiError(400, "bad_body", "ids must be a non-empty list of strings")
        if len(ids) > 100:
            raise ApiError(400, "bad_body", "acknowledge at most 100 alerts at once")
        try:
            with self._session() as client:
                payload = self._alerts_raw(client)
                if payload.get("degraded"):
                    raise UpstreamError("alertmanager", "Alertmanager is not reachable")
                by_id = {}
                for raw in payload.get("alerts") or []:
                    if isinstance(raw, dict) and raw.get("fingerprint"):
                        by_id[str(raw["fingerprint"])] = raw
                missing = [item for item in ids if item not in by_id]
                if missing:
                    raise ApiError(404, "not_found", "unknown alert", {"ids": missing})
                now = self._now_dt()
                end = now + timedelta(hours=_SILENCE_HOURS)
                done = []
                for item in ids:
                    raw = by_id[item]
                    status = raw.get("status") if isinstance(raw.get("status"), dict) else {}
                    if status.get("silencedBy"):
                        done.append(item)
                        continue
                    body = {
                        "matchers": _matchers(raw.get("labels") or {}),
                        "startsAt": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                        "endsAt": end.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                        "createdBy": (created_by or "ie-config")[:200],
                        "comment": "Acknowledged in InsightEngine",
                    }
                    response = self._send(
                        client, "POST", self.settings.alertmanager_url + "/api/v2/silences",
                        json_body=body, headers={"Content-Type": "application/json"}, upstream="alertmanager",
                    )
                    if response.status_code >= 400:
                        raise UpstreamError("alertmanager", "Alertmanager rejected the silence (HTTP %s)" % response.status_code)
                    done.append(item)
                self.cache.drop("am-alerts")
        except UpstreamError as exc:
            raise _as_upstream(exc)
        log.info("alert silence created count=%s", len(done))
        return {"ids": done, "ok": True}

    def metrics(self, device_id: str | None, kind: str, range_key: str, custom_min: int, port_id: str | None = None) -> list:
        window, step = _range_window(range_key, custom_min)
        try:
            with self._session() as client:
                rows, _meta, _degraded = self._decorated(client)
                device = None
                if device_id:
                    found = self._find_device(rows, device_id)
                    if found is None:
                        decoded = unquote(device_id or "").strip()
                        if is_form_key(decoded):
                            return []
                        if netdisco_find(self._netdisco_url(), decoded):
                            return []
                        raise ApiError(404, "not_found", "unknown device")
                    device = found
                selector = self._selector(device["_device"]) if device else ""
                end = self._now()
                start = end - window
                if kind == "throughput":
                    return self._throughput(client, selector, start, end, step, window)
                if kind == "resources":
                    return self._resources(client, selector, start, end, step, window)
                if kind == "top":
                    return self._top_ports(client, selector, window)
                if kind == "port":
                    return self._port_series(client, selector, port_id or "", start, end, step, window)
        except UpstreamError as exc:
            raise _as_upstream(exc)
        raise ApiError(400, "bad_query", "unknown metric")

    def _throughput(self, client, selector: str, start, end, step, window) -> list[dict]:
        if not selector:
            return []
        inbound = self._align(self._prom_range(client, "sum(rate(ifHCInOctets%s[5m])) * 8 / 1000000" % selector, start, end, step))
        outbound = self._align(self._prom_range(client, "sum(rate(ifHCOutOctets%s[5m])) * 8 / 1000000" % selector, start, end, step))
        errors = self._align(self._prom_range(client, "sum(rate(ifInErrors%s[5m])) * 60" % selector, start, end, step))
        return _series(inbound, outbound, errors, window, ("inBps", "outBps", "errors"))

    def _resources(self, client, selector: str, start, end, step, window) -> list[dict]:
        if not selector:
            return []
        cpu = self._align(self._prom_range(
            client,
            "avg(cpmCPUTotal5minRev%s) or avg(fgSysCpuUsage%s)" % (selector, selector),
            start, end, step,
        ))
        mem_query = (
            "(sum(ciscoMemoryPoolUsed%(s)s) / clamp_min(sum(ciscoMemoryPoolUsed%(s)s) + sum(ciscoMemoryPoolFree%(s)s), 1)) * 100 "
            "or avg(fgSysMemUsage%(s)s)"
        ) % {"s": selector}
        mem = self._align(self._prom_range(client, mem_query, start, end, step))
        temp = self._align(self._prom_range(client, "max(ciscoEnvMonTemperatureStatusValue%s)" % selector, start, end, step))
        stamps = sorted(set(cpu) | set(mem) | set(temp))
        points = []
        for ts in stamps:
            points.append({
                "t": int(ts * 1000),
                "label": _label_for(ts, window),
                "cpu": _round(cpu.get(ts)),
                "mem": _round(mem.get(ts)),
                "temp": _round(temp.get(ts)),
            })
        return points

    def _top_ports(self, client, selector: str, window: int) -> list[dict]:
        if not selector:
            return []
        rate_window = "5m"
        if window >= 24 * 3600:
            rate_window = "15m"
        inbound = self._prom(client, "rate(ifHCInOctets%s[%s])" % (selector, rate_window))
        outbound = self._prom(client, "rate(ifHCOutOctets%s[%s])" % (selector, rate_window))
        speed = self._prom(client, "ifHighSpeed%s" % selector)
        speeds = {_iface_id(sample.get("metric") or {}): _sample_value(sample) for sample in speed}
        names = {}
        totals: dict[str, float] = {}
        for sample in inbound + outbound:
            metric = sample.get("metric") or {}
            key = _iface_id(metric)
            if not key:
                continue
            names[key] = _iface_name(metric)
            value = _sample_value(sample) or 0
            totals[key] = totals.get(key, 0) + value * 8
        ranked = []
        for key, bits in totals.items():
            mbps = speeds.get(key) or 0
            util = 0.0
            if mbps and mbps > 0:
                util = min(100.0, bits / (mbps * 1_000_000) * 100)
            ranked.append({"name": names.get(key) or key, "util": round(util, 1)})
        ranked.sort(key=lambda item: item["util"], reverse=True)
        return ranked[:8]

    def _port_series(self, client, selector: str, port_id: str, start, end, step, window) -> list[dict]:
        matcher = _port_matcher(selector, port_id)
        inbound = self._align(self._prom_range(client, "sum(rate(ifHCInOctets%s[5m])) * 8 / 1000000" % matcher, start, end, step))
        outbound = self._align(self._prom_range(client, "sum(rate(ifHCOutOctets%s[5m])) * 8 / 1000000" % matcher, start, end, step))
        errors = self._align(self._prom_range(client, "sum(rate(ifInErrors%s[5m])) * 60" % matcher, start, end, step))
        speed_samples = self._prom(client, "max(ifHighSpeed%s)" % matcher)
        speed = _first_value(speed_samples) or 0
        points = _series(inbound, outbound, errors, window, ("inBps", "outBps", "errors"))
        for point in points:
            inn = point["inBps"]
            out = point["outBps"]
            if speed and inn is not None and out is not None:
                point["util"] = round(min(100.0, ((inn + out) * 1_000_000) / (speed * 1_000_000) * 100), 1)
            else:
                point["util"] = None
        return points

    def _align(self, result: list[dict]) -> dict[float, float]:
        buckets: dict[float, float] = {}
        for series in result:
            for pair in series.get("values") or []:
                try:
                    ts = float(pair[0])
                    val = float(pair[1])
                except (TypeError, ValueError, IndexError):
                    continue
                buckets[ts] = buckets.get(ts, 0.0) + val
        return buckets

    def health(self) -> dict:
        upstreams = {}
        with self._session() as client:
            upstreams["netbox"] = self._probe_netbox(client)
            upstreams["prometheus"] = self._probe_simple(client, self.settings.prometheus_url + "/-/healthy", "prometheus")
            upstreams["alertmanager"] = self._probe_simple(client, self.settings.alertmanager_url + "/-/healthy", "alertmanager")
        ok = all(item["ok"] for item in upstreams.values())
        return {"ok": ok, "status": "ok" if ok else "degraded", "upstreams": upstreams}

    def _probe_netbox(self, client) -> dict:
        headers = netbox_headers(self.settings.netbox_token_file)
        if not headers:
            return {"ok": False, "status": "unconfigured"}
        try:
            response = self._send(
                client, "GET", self.settings.netbox_url + "/api/dcim/devices/?limit=1",
                headers=headers, upstream="netbox",
            )
        except UpstreamError:
            return {"ok": False, "status": "down"}
        if response.status_code == 200:
            return {"ok": True, "status": "ok"}
        if response.status_code in (401, 403):
            return {"ok": False, "status": "unauthorized"}
        return {"ok": False, "status": "down"}

    def _probe_simple(self, client, url: str, upstream: str) -> dict:
        try:
            response = self._send(client, "GET", url, upstream=upstream)
        except UpstreamError:
            return {"ok": False, "status": "down"}
        if response.status_code < 400:
            return {"ok": True, "status": "ok"}
        return {"ok": False, "status": "down"}

    def accept_webhook(self, body, authorization: str) -> dict:
        secret = webhook_secret(self.settings)
        if secret:
            got = ""
            header = authorization or ""
            if header.lower().startswith("bearer "):
                got = header[7:].strip()
            if not _secret_match(got, secret):
                raise ApiError(401, "unauthorized", "missing or invalid token")
        if body is None:
            body = {}
        if not isinstance(body, dict):
            raise ApiError(400, "bad_body", "webhook body must be a JSON object")
        alerts = body.get("alerts")
        received = len(alerts) if isinstance(alerts, list) else 0
        log.info("alert webhook accepted count=%s", received)
        return {"ok": True, "received": received}

    def _paint_ap_face(self, face: dict, hostname: str) -> None:
        """Faceplate 'Offline' is only for a telemetry down, never for a port-less AP."""
        if not isinstance(face, dict) or face.get("form_factor") != "ceiling-ap":
            return
        found = self._ap_for_device_cached(hostname)
        status = str((found or {}).get("status") or "")
        if status == "up":
            face["apState"] = "up"
        elif status == "down":
            face["apState"] = "down"
        else:
            face["apState"] = "unknown"

    def _ap_for_device_cached(self, hostname: str) -> dict | None:
        cached = self.cache.get("ap-snapshot")
        if not cached:
            return None
        wanted = (hostname or "").strip()
        mac = canon_mac(wanted)
        for row in cached.get("rows") or []:
            same_name = str(row.get("name") or "").lower() == wanted.lower()
            same_mac = bool(mac) and canon_mac(str(row.get("mac") or "")) == mac
            if same_name or same_mac:
                return row
        return None

    def _ap_for_device(self, client, hostname: str) -> dict | None:
        """Telemetry for one AP. MAC and hostname both match. Online comes from the snapshot."""
        wanted = (hostname or "").strip()
        if not wanted:
            return None
        cached = self.cache.get("ap-snapshot")
        if cached is None:
            try:
                self.list_access_points(page=1, page_size=1, q="", wlc="", site="", status="")
            except Exception:
                cached = None
            cached = self.cache.get("ap-snapshot") or cached
        mac = canon_mac(wanted)
        for row in (cached or {}).get("rows") or []:
            same_name = str(row.get("name") or "").lower() == wanted.lower()
            same_mac = bool(mac) and canon_mac(str(row.get("mac") or "")) == mac
            if same_name or same_mac:
                return {
                    "status": row.get("status") or "",
                    "clients": row.get("clients"),
                    "uptimeSeconds": row.get("uptimeSeconds"),
                    "radios": list(row.get("radios") or []),
                }
        safe = prom_escape(wanted)
        clients = self._prom(client, 'ie_wlc_ap_clients{ap_name="%s"} or sum(ie_wlc_radio_clients{ap_name="%s"})' % (safe, safe))
        uptime = self._prom(client, 'ie_wlc_ap_uptime_centiseconds{ap_name="%s"}' % safe)
        radios = self._join_ap_radios(
            self._prom(client, 'ie_wlc_radio_channel{ap="%s"} or ie_wlc_radio_channel{ap_name="%s"}' % (safe, safe)),
            self._prom(client, 'ie_wlc_radio_channel_util{ap="%s"} or ie_wlc_radio_channel_util{ap_name="%s"}' % (safe, safe)),
            self._prom(client, 'ie_wlc_radio_clients{ap="%s"} or ie_wlc_radio_clients{ap_name="%s"}' % (safe, safe)),
        )
        seconds = _first_value(uptime)
        if seconds is not None:
            seconds = float(seconds) / 100.0
        return {
            "status": "",
            "clients": _first_value(clients),
            "uptimeSeconds": seconds,
            "radios": radios,
        }

    def _join_ap_radios(self, channels, utils, clients) -> list[dict]:
        by_slot: dict[str, dict] = {}

        def slot_of(sample: dict) -> str:
            metric = sample.get("metric") or {}
            return str(metric.get("slot") or metric.get("index") or "")

        for sample in channels or []:
            key = slot_of(sample)
            by_slot.setdefault(key, {"slot": key, "channel": None, "utilization": None, "clients": None})
            by_slot[key]["channel"] = _sample_value(sample)
        for sample in utils or []:
            key = slot_of(sample)
            by_slot.setdefault(key, {"slot": key, "channel": None, "utilization": None, "clients": None})
            value = _sample_value(sample)
            by_slot[key]["utilization"] = None if value is None else round(float(value) / 100.0, 4)
        for sample in clients or []:
            key = slot_of(sample)
            by_slot.setdefault(key, {"slot": key, "channel": None, "utilization": None, "clients": None})
            by_slot[key]["clients"] = _sample_value(sample)
        return [by_slot[key] for key in sorted(by_slot)]

    def list_access_points(self, *, page: int, page_size: int, q: str, wlc: str, site: str, status: str) -> dict:
        cached = self.cache.get("ap-snapshot")
        degraded = []
        if cached is None:
            try:
                with self._session() as client:
                    cached = self._ap_snapshot(client)
                    try:
                        devices = self._devices_raw(client)
                    except UpstreamError:
                        devices = []
                    attach_netbox_sites(cached.get("rows") or [], devices)
                    _annotate_access_points(cached.get("rows") or [], devices)
            except UpstreamError:
                cached = {"rows": [], "degraded": True}
            self.cache.put("ap-snapshot", cached)
        if cached.get("degraded"):
            degraded = ["prometheus"]
        body = page_rows(cached.get("rows") or [], page=page, page_size=page_size, q=q, wlc=wlc, site=site, status=status)
        if degraded:
            body["degraded"] = degraded
        return body

    def _ap_snapshot(self, client) -> dict:
        try:
            status = self._prom(client, "ie_wlc_ap_admin_status or ie_wlc_ap_oper_status or ie_wlc_ap_oper_up")
            radio_oper = self._prom(client, "ie_wlc_radio_oper_up or ie_wlc_radio_oper_status")
            clients = self._prom(client, "ie_wlc_ap_clients or ie_wlc_client_radio_clients")
            uptime = self._prom(client, "ie_wlc_ap_uptime_centiseconds")
            channels = self._prom(client, "ie_wlc_radio_channel")
            utils = self._prom(client, "ie_wlc_radio_channel_util")
            radio_clients = self._prom(client, "ie_wlc_radio_clients")
            info = self._prom(client, "ie_wlc_ap_info or ie_wlc_ap_info_info")
            noise = self._prom(client, "ie_wlc_radio_noise")
            interference = self._prom(client, "ie_wlc_radio_interference")
            power = self._prom(client, "ie_wlc_radio_tx_power_dbm or ie_wlc_radio_tx_power")
            width = self._prom(client, "ie_wlc_radio_width")
            rssi = self._prom(client, "ie_wlc_client_radio_rssi_avg")
            snr = self._prom(client, "ie_wlc_client_radio_snr_avg")
            ssids = self._prom(client, "ie_wlc_ssid_clients")
            neighbors = self._prom(client, "ie_wlc_neighbor_info")
        except UpstreamError:
            return {"rows": [], "degraded": True}
        rows: dict[int, dict] = {}
        by_mac: dict[tuple, dict] = {}
        by_name: dict[tuple, dict] = {}
        now = self._now()

        def _blank(name: str, mac: str, wlc: str, site: str) -> dict:
            return {
                "name": name or mac or "unknown",
                "mac": mac,
                "wlc": wlc,
                "site": site,
                "status": "unknown",
                "clients": None,
                "uptimeSeconds": None,
                "radios": [],
                "model": "",
                "serial": "",
                "ip": "",
                "location": "",
                "ios": "",
                "mode": "",
                "siteTag": "",
                "policyTag": "",
                "rfTag": "",
                "neighborSwitch": "",
                "neighborPort": "",
                "netboxSite": "",
                "ssids": [],
                "rssiAvg": None,
                "snrAvg": None,
                "_explicit": None,
                "_fresh": False,
            }

        def _absorb(row: dict, name: str, mac: str, wlc: str, site: str) -> None:
            if mac and not row.get("mac"):
                row["mac"] = mac
            if name and not looks_like_mac(name) and (not row.get("name") or looks_like_mac(row.get("name") or "")):
                row["name"] = name
            if site and not row.get("site"):
                row["site"] = site
            if wlc and not row.get("wlc"):
                row["wlc"] = wlc
            if row.get("mac"):
                by_mac[(row["wlc"], row["mac"])] = row
            if row.get("name") and not looks_like_mac(row["name"]):
                by_name[(row["wlc"], row["name"].lower())] = row

        def ensure(metric: dict) -> dict:
            name, mac, wlc, site = _ap_identity(metric)
            row = by_mac.get((wlc, mac)) if mac else None
            if row is None and name:
                named = by_name.get((wlc, name.lower()))
                # A second MAC for the same hostname stays its own row.
                if named is not None and (not mac or not named.get("mac")):
                    row = named
            if row is None:
                row = _blank(name, mac, wlc, site)
                rows[id(row)] = row
            _absorb(row, name, mac, wlc, site)
            return row

        def note_state(row: dict, metric: dict, value, fresh: bool) -> None:
            found = explicit_status(metric, value)
            if found == "down":
                row["_explicit"] = "down"
            elif found == "up" and row.get("_explicit") != "down":
                row["_explicit"] = "up"
            labeled = capwap_state(metric)
            if labeled == "down":
                row["_explicit"] = "down"
            elif labeled == "up" and row.get("_explicit") != "down":
                row["_explicit"] = "up"
            if fresh and row.get("_explicit") != "down":
                row["_fresh"] = True

        for sample in status:
            metric = sample.get("metric") or {}
            row = ensure(metric)
            note_state(row, metric, _sample_value(sample), sample_fresh(sample, now))
        for sample in radio_oper:
            metric = sample.get("metric") or {}
            row = ensure(metric)
            note_state(row, metric, _sample_value(sample), sample_fresh(sample, now))
        radio_client_sum: dict[int, float] = {}
        for sample in clients:
            metric = sample.get("metric") or {}
            row = ensure(metric)
            value = _sample_value(sample)
            name = str(metric.get("__name__") or "")
            if name == "ie_wlc_client_radio_clients":
                if value is not None:
                    radio_client_sum[id(row)] = radio_client_sum.get(id(row), 0) + float(value)
            else:
                row["clients"] = value
        for key, total in radio_client_sum.items():
            row = rows.get(key)
            if row is not None and row["clients"] is None:
                row["clients"] = total
        for sample in uptime:
            metric = sample.get("metric") or {}
            row = ensure(metric)
            value = _sample_value(sample)
            row["uptimeSeconds"] = None if value is None else round(float(value) / 100.0, 1)
        radio_by: dict[tuple, dict] = {}
        for sample in list(channels) + list(utils) + list(radio_clients) + list(noise) + list(interference) + list(power) + list(width) + list(rssi) + list(snr):
            metric = sample.get("metric") or {}
            row = ensure(metric)
            if sample_fresh(sample, now):
                note_state(row, metric, _sample_value(sample), True)
            slot = str(metric.get("slot") or metric.get("radio") or "")
            key = (id(row), slot)
            radio = radio_by.setdefault(key, {
                "slot": slot, "channel": None, "utilization": None, "clients": None,
                "noise": None, "interference": None, "txPowerDbm": None, "width": None,
                "rssiAvg": None, "snrAvg": None, "band": str(metric.get("band") or ""),
                "owner": row,
            })
            value = _sample_value(sample)
            metric_name = str(metric.get("__name__") or "")
            if metric_name.endswith("channel") and "util" not in metric_name:
                radio["channel"] = value
            elif "util" in metric_name:
                radio["utilization"] = None if value is None else round(float(value) / 100.0, 4)
            elif "clients" in metric_name and "poor" not in metric_name:
                radio["clients"] = value
            elif metric_name.endswith("noise"):
                radio["noise"] = value
            elif "interference" in metric_name:
                radio["interference"] = value
            elif "tx_power" in metric_name:
                radio["txPowerDbm"] = value
            elif metric_name.endswith("width"):
                radio["width"] = value
            elif "rssi" in metric_name:
                radio["rssiAvg"] = value
            elif "snr" in metric_name:
                radio["snrAvg"] = value
        for sample in info or []:
            metric = sample.get("metric") or {}
            row = ensure(metric)
            note_state(row, metric, _sample_value(sample), sample_fresh(sample, now))
            ios = str(metric.get("ios") or metric.get("sw_version") or "")
            for src, dst in (("model", "model"), ("serial", "serial"), ("ip", "ip"), ("location", "location"), ("mode", "mode")):
                if metric.get(src):
                    row[dst] = str(metric.get(src))
            if ios:
                row["ios"] = ios
            if metric.get("mac") or metric.get("wtp_mac"):
                row["mac"] = canon_mac(str(metric.get("mac") or metric.get("wtp_mac"))) or row.get("mac") or ""
            for src, dst in (("site_tag", "siteTag"), ("policy_tag", "policyTag"), ("rf_tag", "rfTag")):
                if metric.get(src):
                    row[dst] = str(metric.get(src))
        for sample in neighbors or []:
            metric = sample.get("metric") or {}
            row = ensure(metric)
            if metric.get("switch"):
                row["neighborSwitch"] = str(metric.get("switch"))
            if metric.get("port"):
                row["neighborPort"] = str(metric.get("port"))
        ssid_rows: dict[int, list] = {}
        for sample in ssids or []:
            metric = sample.get("metric") or {}
            row = ensure(metric)
            ssid_rows.setdefault(id(row), []).append({
                "ssid": str(metric.get("ssid") or ""),
                "radio": str(metric.get("radio") or metric.get("slot") or ""),
                "band": str(metric.get("band") or ""),
                "clients": _sample_value(sample),
            })
        grouped: dict[int, list] = {}
        for radio in radio_by.values():
            owner = radio.pop("owner")
            grouped.setdefault(id(owner), []).append(radio)
        for key, radios in grouped.items():
            row = rows.get(key)
            if row is None:
                continue
            row["radios"] = radios
            rssi_vals = [item["rssiAvg"] for item in radios if item.get("rssiAvg") is not None]
            snr_vals = [item["snrAvg"] for item in radios if item.get("snrAvg") is not None]
            if rssi_vals:
                row["rssiAvg"] = round(sum(rssi_vals) / len(rssi_vals), 1)
            if snr_vals:
                row["snrAvg"] = round(sum(snr_vals) / len(snr_vals), 1)
        for key, items in ssid_rows.items():
            row = rows.get(key)
            if row is not None:
                row["ssids"] = items
        ordered = []
        for row in rows.values():
            row["status"] = finish_ap_status(row.get("_explicit"), bool(row.get("_fresh")))
            row.pop("_explicit", None)
            row.pop("_fresh", None)
            if not row.get("name"):
                row["name"] = row.get("mac") or "unknown"
            ordered.append(row)
        ordered.sort(key=lambda item: (str(item["wlc"]).lower(), str(item["name"]).lower(), str(item["mac"]).lower()))
        return {"rows": ordered, "degraded": False}

    def access_point_detail(self, wlc: str, name: str) -> dict:
        wanted_wlc = (wlc or "").strip()
        wanted_name = (name or "").strip()
        if not wanted_name:
            raise ApiError(404, "not_found", "unknown access point")
        listing = self.list_access_points(page=1, page_size=1, q="", wlc="", site="", status="")
        cached = self.cache.get("ap-snapshot") or {}
        row = None
        wanted_mac = canon_mac(wanted_name)
        for item in cached.get("rows") or []:
            if wanted_wlc and wanted_wlc.lower() not in str(item.get("wlc") or "").lower():
                continue
            same_name = str(item.get("name") or "").lower() == wanted_name.lower()
            same_mac = bool(wanted_mac) and canon_mac(str(item.get("mac") or "")) == wanted_mac
            if same_mac or same_name:
                row = item
                if same_mac:
                    break
        if row is None:
            raise ApiError(404, "not_found", "unknown access point")
        events = []
        degraded = list(listing.get("degraded") or [])
        try:
            with self._session() as client:
                end = self._now_dt().timestamp()
                start = end - 6 * 3600
                safe_ap = prom_escape(wanted_name)
                safe_wlc = prom_escape(row.get("wlc") or "")
                selector = '{ap="%s",wlc="%s"}' % (safe_ap, safe_wlc)
                oper = self._prom_range(client, "ie_wlc_ap_oper_up%s" % selector, start, end, 60)
                channel = self._prom_range(client, "ie_wlc_radio_channel%s" % selector, start, end, 60)
                power = self._prom_range(client, "ie_wlc_radio_tx_power_dbm%s" % selector, start, end, 60)
                events = events_from_range(oper, "oper") + events_from_range(channel, "channel") + events_from_range(power, "tx power")
                events.sort(key=lambda item: item["t"])
        except UpstreamError:
            degraded.append("prometheus")
        return {"accessPoint": row, "events": events[-50:], "degraded": degraded}


def _title(upstream: str) -> str:
    return {"netbox": "NetBox", "prometheus": "Prometheus", "alertmanager": "Alertmanager"}.get(upstream, upstream)


def _parse_sort(sort: str) -> tuple[str, str]:
    text = (sort or "hostname:asc").strip()
    if ":" in text:
        key, _, direction = text.partition(":")
    else:
        key, direction = text, "asc"
    if key not in _ROW_SORT:
        key = "hostname"
    direction = "desc" if direction.lower() == "desc" else "asc"
    return key, direction


def _sort_value(row: dict, key: str):
    if key == "health":
        return _HEALTH_RANK.get(row["health"], 9)
    if key == "uptime":
        return row.get("uptime_s", -1)
    if key == "lastPoll":
        return row.get("last_age", 10**12)
    if key in _NUMERIC_SORT:
        return row.get(key, 0)
    return str(row.get(key) or "").lower()


def _first_value(samples: list[dict]):
    for sample in samples:
        value = _sample_value(sample)
        if value is not None:
            return value
    return None


def _metric_names(metric: dict) -> list[str]:
    found = []
    for field in ("ifName", "ifDescr", "ifAlias"):
        value = str(metric.get(field) or "").strip()
        if value and value not in found:
            found.append(value)
    return found


def _sample_keys(metric: dict) -> list[str]:
    """ifIndex first, then every long/short form of ifName, ifDescr and ifAlias."""
    keys = []
    if metric.get("ifIndex") not in (None, ""):
        keys.append("idx:" + str(metric.get("ifIndex")))
    for name in _metric_names(metric):
        for key in iface_match_keys(name):
            keys.append("name:" + key)
    return keys


def _put_joined(bucket: dict, metric: dict, value) -> None:
    for key in _sample_keys(metric):
        bucket.setdefault(key, value)


def _get_joined(bucket: dict, metric: dict, default=None):
    for key in _sample_keys(metric):
        if key in bucket:
            return bucket[key]
    return default


def _latest_stamp(samples) -> str:
    latest = None
    for sample in samples or []:
        try:
            stamp = float((sample.get("value") or [None])[0])
        except (TypeError, ValueError, IndexError):
            continue
        if latest is None or stamp > latest:
            latest = stamp
    if latest is None:
        return ""
    return datetime.fromtimestamp(latest, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _drop_rate(drop_in: dict, drop_out: dict, metric: dict):
    left = _get_joined(drop_in, metric, None)
    right = _get_joined(drop_out, metric, None)
    if left is None and right is None:
        return None
    return round(float(left or 0) + float(right or 0), 4)


def _join_ports(oper, admin, speed, inbound, outbound, errors, discards_in=None, discards_out=None) -> list[dict]:
    admin_by = {}
    for sample in admin:
        metric = sample.get("metric") or {}
        if _sample_keys(metric):
            _put_joined(admin_by, metric, _admin_state(sample))
    speed_by = {}
    for sample in speed:
        metric = sample.get("metric") or {}
        if _sample_keys(metric):
            _put_joined(speed_by, metric, _sample_value(sample) or 0)
    in_by = {}
    for sample in inbound:
        metric = sample.get("metric") or {}
        if _sample_keys(metric):
            _put_joined(in_by, metric, (_sample_value(sample) or 0) * 8)
    out_by = {}
    for sample in outbound:
        metric = sample.get("metric") or {}
        if _sample_keys(metric):
            _put_joined(out_by, metric, (_sample_value(sample) or 0) * 8)
    err_by = {}
    for sample in errors:
        metric = sample.get("metric") or {}
        if _sample_keys(metric):
            _put_joined(err_by, metric, (_sample_value(sample) or 0) * 300)
    drop_in = {}
    for sample in discards_in or []:
        metric = sample.get("metric") or {}
        if _sample_keys(metric):
            _put_joined(drop_in, metric, _sample_value(sample) or 0)
    drop_out = {}
    for sample in discards_out or []:
        metric = sample.get("metric") or {}
        if _sample_keys(metric):
            _put_joined(drop_out, metric, _sample_value(sample) or 0)
    seen = set()
    ports = []
    for sample in oper:
        metric = sample.get("metric") or {}
        key = _iface_id(metric)
        if not key or key in seen:
            continue
        seen.add(key)
        name = _iface_name(metric)
        names = _metric_names(metric) or ([name] if name else [])
        mbps = _get_joined(speed_by, metric, 0) or 0
        bits_in = _get_joined(in_by, metric, 0) or 0
        bits_out = _get_joined(out_by, metric, 0) or 0
        util = 0.0
        if mbps and mbps > 0:
            util = min(100.0, (bits_in + bits_out) / (mbps * 1_000_000) * 100)
        err = _get_joined(err_by, metric, 0) or 0
        state = _port_state(_oper_state(sample), _get_joined(admin_by, metric), err, util)
        port = {
            "id": key,
            "name": name,
            "names": names,
            "type": port_type_for(name),
            "speed": speed_text(mbps, state),
            "state": state,
            "utilisation": round(util, 1),
            "errors": int(round(err)),
            "inBps": round(bits_in, 1),
            "outBps": round(bits_out, 1),
            "dropsRate": _drop_rate(drop_in, drop_out, metric),
            "alias": str(metric.get("ifAlias") or ""),
            "description": str(metric.get("ifDescr") or ""),
        }
        ports.append(port)
    ports.sort(key=lambda item: item["name"].lower())
    return ports


def _minimal_detail(row: dict, now: datetime) -> dict:
    return {
        "id": row.get("id") or "",
        "hostname": row.get("hostname") or "",
        "role": row.get("role") or "",
        "site": row.get("site") or "",
        "siteId": row.get("siteId") or "",
        "mgmtIp": row.get("mgmtIp") or "—",
        "modelFamily": row.get("modelFamily") or "—",
        "health": row.get("health") or "unreachable",
        "status": row.get("status") or "active",
        "uptime": row.get("uptime") or "—",
        "lastPoll": row.get("lastPoll") or "—",
        "firmware": "—",
        "serialMasked": "—",
        "faceplate": {
            "form_factor": row.get("formFactor") or "generic",
            "role": row.get("role") or "",
            "hostname": row.get("hostname") or "",
            "ports": [],
        },
        "issues": [],
        "checks": [],
        "hardware": [],
        "checkRunAt": _clock_stamp(now),
        "_port_degraded": True,
    }


_SECRET_LINE = re.compile(r"(?i)(password|secret|community|passphrase|private-key|\bpsk\b)")


def redact_config(text: str) -> str:
    """Drop secret-looking values from a config backup before it leaves ie-config."""
    if not text:
        return ""
    lines = []
    for line in text.splitlines():
        lines.append("***" if _SECRET_LINE.search(line) else line)
    return "\n".join(lines)[:20000]


def _public_interface(raw: dict) -> dict:
    kind = raw.get("type")
    if isinstance(kind, dict):
        kind_text = str(kind.get("label") or kind.get("value") or "")
    else:
        kind_text = str(kind or "")
    return {
        "name": str(raw.get("name") or ""),
        "type": kind_text,
        "enabled": bool(raw.get("enabled", True)),
        "mac": str(raw.get("mac_address") or ""),
        "description": str(raw.get("description") or ""),
        "criticalPath": mark_critical_interface(raw),
    }


def _public_address(raw: dict) -> dict:
    assigned = raw.get("assigned_object") if isinstance(raw.get("assigned_object"), dict) else {}
    status = raw.get("status") if isinstance(raw.get("status"), dict) else {}
    return {
        "address": str(raw.get("address") or ""),
        "interface": str(assigned.get("name") or assigned.get("display") or ""),
        "status": str(status.get("label") or status.get("value") or ""),
    }


def _match_record(rows: list[dict], device_id: str, *, name_key: str, ip_key: str, suffixes: list[str] | None = None) -> dict | None:
    """Resolve a device by NetBox id, then name, then primary IP.

    A faceplate form key is never treated as a name. That used to return the
    first device of that form. Names match after the configured DNS suffix is
    removed, so a Netdisco FQDN hits the short NetBox hostname.
    """
    key = unquote(device_id or "").strip()
    if not key:
        return None
    for row in rows:
        if str(row.get("id") or "") == key:
            return row
    if is_form_key(key):
        return None
    for row in rows:
        if names_match(str(row.get(name_key) or ""), key, suffixes):
            return row
    ip = key.split("/")[0].strip()
    if not ip:
        return None
    for row in rows:
        if str(row.get(ip_key) or "").split("/")[0] == ip:
            return row
    return None


def _netbox_facts(device: dict) -> dict:
    return {
        "role_slug": device.get("role_slug") or "",
        "role_name": device.get("role_name") or "",
        "model": device.get("model") or "",
        "manufacturer": device.get("manufacturer") or "",
        "hostname": device.get("name") or device.get("hostname") or "",
        "serial": device.get("serial") or "",
        "platform": device.get("platform") or "",
        "site": device.get("site_name") or device.get("site") or "",
        "sw_version": device.get("sw_version") or "",
        "part_number": device.get("part_number") or "",
    }


def _index_hit(index: dict, ip: str, name: str, suffixes: list[str] | None = None) -> dict | None:
    if not index:
        return None
    by_ip = index.get("by_ip") or {}
    by_name = index.get("by_name") or {}
    if ip and ip in by_ip:
        return by_ip[ip]
    for label in ((name or "").strip(), strip_hostname(name or "", suffixes)):
        lowered = label.lower()
        if lowered and lowered in by_name:
            return by_name[lowered]
    return None


def _empty_netdisco(reason: str) -> dict:
    return {"available": False, "reason": reason, "device": None, "ports": [], "neighbors": []}


def _netdisco_device_row(row: tuple) -> dict:
    ip, dns, name, description, vendor, model, os_name, os_ver, serial = row[:9]
    location = ""
    port_count = 0
    if len(row) >= 11:
        location = str(row[9] or "")
        try:
            port_count = int(row[10] or 0)
        except (TypeError, ValueError):
            port_count = 0
    elif len(row) == 10:
        location = str(row[9] or "")
    return {
        "ip": str(ip or ""),
        "dns": str(dns or ""),
        "name": str(name or ""),
        "description": str(description or ""),
        "vendor": str(vendor or ""),
        "model": str(model or ""),
        "os": str(os_name or ""),
        "os_ver": str(os_ver or ""),
        "serial": str(serial or ""),
        "location": location,
        "port_count": port_count,
    }


def netdisco_index(database_url: str, suffixes: list[str] | None = None) -> dict:
    """Vendor, model and port counts from Netdisco, keyed by IP and name."""
    empty = {"by_ip": {}, "by_name": {}}
    if not database_url:
        return empty
    try:
        import psycopg
        with psycopg.connect(database_url, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT host(ip)::text, COALESCE(dns, ''), COALESCE(name, ''), "
                    "COALESCE(description, ''), COALESCE(vendor, ''), COALESCE(model, ''), "
                    "COALESCE(os, ''), COALESCE(os_ver, ''), COALESCE(serial, ''), COALESCE(location, '') FROM device"
                )
                devices = cur.fetchall()
                cur.execute("SELECT host(ip)::text, count(*) FROM device_port GROUP BY host(ip)::text")
                counts = {str(ip or ""): int(total or 0) for ip, total in cur.fetchall()}
    except Exception:
        log.warning("netdisco device index could not be read")
        return empty
    by_ip: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    for raw in devices:
        item = _netdisco_device_row(tuple(raw) + (counts.get(str(raw[0] or ""), 0),))
        if item["ip"]:
            by_ip[item["ip"]] = item
        for label in (item["dns"], item["name"]):
            if not label:
                continue
            by_name.setdefault(label.lower(), item)
            short = strip_hostname(label, suffixes).lower()
            if short:
                by_name.setdefault(short, item)
    return {"by_ip": by_ip, "by_name": by_name}


def _name_variants(label: str, address: str, suffixes: list[str] | None) -> list[str]:
    wanted = []
    for raw in (label, address, strip_hostname(label, suffixes), strip_hostname(address, suffixes)):
        text = (raw or "").strip().lower()
        if text and text not in wanted:
            wanted.append(text)
    return wanted


def netdisco_snapshot(database_url: str, ip: str = "", name: str = "", suffixes: list[str] | None = None) -> dict:
    """One Netdisco device, its ports, and LLDP/CDP neighbours."""
    suffixes = list(suffixes or [])
    address = (ip or "").split("/")[0].strip()
    label = (name or "").strip()
    if not database_url:
        return _empty_netdisco("Netdisco is not configured")
    if not address and not label:
        return _empty_netdisco("This device has no address to look up in Netdisco")
    wanted = _name_variants(label, address, suffixes)
    pattern = suffix_pattern(suffixes)
    try:
        import psycopg
        with psycopg.connect(database_url, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT host(ip)::text, COALESCE(dns, ''), COALESCE(name, ''), "
                    "COALESCE(description, ''), COALESCE(vendor, ''), COALESCE(model, ''), "
                    "COALESCE(os, ''), COALESCE(os_ver, ''), COALESCE(serial, ''), COALESCE(location, '') "
                    "FROM device WHERE host(ip)::text = %s "
                    "OR lower(COALESCE(dns, '')) = ANY(%s) "
                    "OR lower(COALESCE(name, '')) = ANY(%s) "
                    "OR (%s <> '' AND lower(regexp_replace(COALESCE(dns, ''), %s, '', 'i')) = ANY(%s)) "
                    "OR (%s <> '' AND lower(regexp_replace(COALESCE(name, ''), %s, '', 'i')) = ANY(%s)) "
                    "ORDER BY CASE WHEN host(ip)::text = %s THEN 0 ELSE 1 END LIMIT 1",
                    (address, wanted, wanted, pattern, pattern, wanted, pattern, pattern, wanted, address),
                )
                found = cur.fetchone()
                if not found:
                    return {
                        "available": True,
                        "reason": "Netdisco has not discovered this device yet",
                        "device": None,
                        "ports": [],
                        "neighbors": [],
                    }
                device = _netdisco_device_row(tuple(found))
                cur.execute(
                    "SELECT COALESCE(port, ''), COALESCE(name, ''), COALESCE(descr, ''), "
                    "COALESCE(type, ''), COALESCE(speed::text, ''), COALESCE(up, ''), COALESCE(up_admin, ''), "
                    "COALESCE(host(remote_ip)::text, ''), COALESCE(remote_port, ''), "
                    "COALESCE(remote_id, ''), COALESCE(remote_type, '') "
                    "FROM device_port WHERE host(ip)::text = %s ORDER BY port",
                    (device["ip"],),
                )
                port_rows = cur.fetchall()
    except Exception:
        log.warning("netdisco device read failed")
        return _empty_netdisco("Netdisco could not be read")
    ports = []
    neighbors = []
    for port, port_name, descr, kind, speed, up, up_admin, remote_ip, remote_port, remote_id, remote_type in port_rows:
        item = {
            "port": str(port or ""),
            "name": str(port_name or port or ""),
            "descr": str(descr or ""),
            "type": str(kind or ""),
            "speed": speed,
            "up": str(up or ""),
            "admin": str(up_admin or ""),
            "remoteAddress": str(remote_ip or ""),
            "remotePort": str(remote_port or ""),
            "remoteName": str(remote_id or ""),
            "protocol": str(remote_type or ""),
        }
        ports.append(item)
        remote_name = strip_hostname(item["remoteName"], suffixes)
        item["remoteName"] = remote_name
        if item["remoteAddress"] or remote_name:
            neighbors.append({
                "localPort": item["name"],
                "remoteAddress": item["remoteAddress"],
                "remotePort": item["remotePort"],
                "remoteName": remote_name,
                "protocol": item["protocol"],
                "source": "netdisco",
            })
    device["dns"] = strip_hostname(device.get("dns") or "", suffixes)
    device["name"] = strip_hostname(device.get("name") or "", suffixes)
    device["port_count"] = len(ports)
    return {"available": True, "reason": "", "device": device, "ports": ports, "neighbors": neighbors}


def netdisco_find(database_url: str, key: str, suffixes: list[str] | None = None) -> dict | None:
    """Netdisco device for an id that NetBox did not have. None when it is not there."""
    text = unquote(key or "").strip()
    if not text or not database_url or is_form_key(text):
        return None
    snap = netdisco_snapshot(database_url, ip=text, name=text, suffixes=suffixes)
    if not snap.get("available") or not snap.get("device"):
        return None
    return snap


def netdisco_neighbors(database_url: str, ip: str, suffixes: list[str] | None = None) -> dict:
    """LLDP/CDP neighbours from Netdisco device_port, when that database is set."""
    snap = netdisco_snapshot(database_url, ip=ip, suffixes=suffixes)
    return {
        "available": bool(snap.get("available")),
        "reason": snap.get("reason") or "",
        "neighbors": snap.get("neighbors") or [],
    }


def _ports_from_faceplate(face: dict) -> list[dict]:
    if not isinstance(face, dict):
        return []
    if face.get("members"):
        ports = []
        for member in face.get("members") or []:
            ports.extend(member.get("ports") or [])
        return ports
    if face.get("modules"):
        ports = []
        for module in face.get("modules") or []:
            ports.extend(module.get("ports") or [])
        return ports
    return list(face.get("ports") or [])


def _port_keys(port: dict) -> set[str]:
    keys: set[str] = set()
    labels = [port.get("name"), port.get("port"), port.get("descr"), port.get("localPort")]
    labels.extend(port.get("names") or [])
    for label in labels:
        keys |= iface_match_keys(str(label or ""))
    return keys


def _index_by_port(rows: list[dict] | None) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        for key in _port_keys(row):
            index.setdefault(key, row)
    return index


def _overlay_port_state(ports: list[dict], prom_ports: list[dict]) -> list[dict]:
    by_name = _index_by_port(prom_ports)
    for port in ports:
        prom = None
        for key in iface_match_keys(str(port.get("name") or "")):
            prom = by_name.get(key)
            if prom:
                break
        if not prom:
            continue
        if prom.get("state"):
            port["state"] = prom["state"]
        port["utilisation"] = prom.get("utilisation") or 0
        port["errors"] = prom.get("errors") or 0
        if prom.get("speed") and prom.get("speed") != "—":
            port["speed"] = prom["speed"]
        if prom.get("id"):
            port["id"] = prom["id"]
        if "inBps" in prom:
            port["inBps"] = prom.get("inBps") or 0
        if "outBps" in prom:
            port["outBps"] = prom.get("outBps") or 0
        if prom.get("type") in ("SFP", "SFP+", "QSFP", "MGMT", "CONSOLE", "USB"):
            port["type"] = prom["type"]
        fields = _interface_fields(port, prom)
        if fields["names"]:
            port["names"] = fields["names"]
        if fields["description"]:
            port["description"] = fields["description"]
    return ports


def _annotate_interfaces(interfaces: list[dict], prom_ports: list[dict]) -> None:
    """Add the short/long interface name and the live description to each row."""
    by_name = _index_by_port(prom_ports)
    for row in interfaces or []:
        if not isinstance(row, dict):
            continue
        prom = None
        for key in iface_match_keys(str(row.get("name") or "")):
            prom = by_name.get(key)
            if prom:
                break
        fields = _interface_fields(row, prom)
        if fields["names"]:
            row["names"] = fields["names"]
        if fields["description"]:
            row["description"] = fields["description"]


def _overlay_neighbours(ports: list[dict], nd_ports: list[dict], rows: list[dict], snmp_neighbors: list[dict] | None = None, suffixes: list[str] | None = None) -> list[dict]:
    suffixes = list(suffixes or [])
    nd_index = _index_by_port(nd_ports)
    snmp_index = _index_by_port(snmp_neighbors)
    for port in ports:
        raw = None
        snmp = None
        for key in iface_match_keys(str(port.get("name") or "")):
            if raw is None and key in nd_index:
                raw = nd_index[key]
            if snmp is None and key in snmp_index:
                snmp = snmp_index[key]
        remote = ""
        remote_port = ""
        remote_ip = ""
        source = ""
        if raw and (raw.get("remoteName") or raw.get("remoteAddress")):
            remote = strip_hostname(str(raw.get("remoteName") or ""), suffixes)
            remote_port = str(raw.get("remotePort") or "")
            remote_ip = str(raw.get("remoteAddress") or "")
            source = "netdisco"
        elif snmp and (snmp.get("remoteName") or snmp.get("remoteAddress")):
            remote = strip_device_label(str(snmp.get("remoteName") or ""), suffixes)
            remote_port = str(snmp.get("remotePort") or "")
            remote_ip = str(snmp.get("remoteAddress") or "")
            source = str(snmp.get("source") or snmp.get("protocol") or "snmp")
        elif isinstance(port.get("neighbour"), dict):
            remote = strip_hostname(str(port["neighbour"].get("device") or ""), suffixes)
            remote_port = str(port["neighbour"].get("port") or "")
            source = str(port["neighbour"].get("source") or "")
        if not remote and not remote_ip:
            continue
        match = _match_record(rows, remote, name_key="hostname", ip_key="mgmtIp", suffixes=suffixes) if remote else None
        if match is None and remote_ip:
            match = _match_record(rows, remote_ip, name_key="hostname", ip_key="mgmtIp", suffixes=suffixes)
        neighbour = {
            "device": remote or remote_ip,
            "port": remote_port,
            "deviceId": match["id"] if match else "",
            "role": str((match or {}).get("role") or ""),
            "formFactor": str((match or {}).get("formFactor") or ""),
        }
        if source:
            neighbour["source"] = source
        port["neighbour"] = neighbour
    return ports


def _detail_from_netdisco(snap: dict, now: datetime) -> dict:
    device = snap.get("device") or {}
    payload = dict(device)
    payload["ports"] = snap.get("ports") or []
    classified = classify_device(None, payload)
    hostname = device.get("dns") or device.get("name") or device.get("ip") or "—"
    model = device.get("model") or ""
    ports = _overlay_neighbours(list(classified["ports"]), snap.get("ports") or [], [])
    form = classified["form"] if classified["form"] in FORM_FACTORS else "generic"
    face = _faceplate(form, classified["role"], hostname, model, ports)
    firmware = " ".join(part for part in (device.get("os") or "", device.get("os_ver") or "") if part).strip()
    comparison = dict(classified["comparison"])
    comparison["faceplateSource"] = classified["faceplate_source"] if ports else "none"
    return {
        "id": device.get("ip") or hostname,
        "hostname": hostname,
        "role": classified["role"],
        "site": "—",
        "siteId": "",
        "mgmtIp": device.get("ip") or "—",
        "modelFamily": model or "—",
        "health": "unreachable",
        "status": "netdisco-only",
        "netdiscoOnly": True,
        "uptime": "—",
        "lastPoll": "—",
        "firmware": firmware or "—",
        "serialMasked": display_serial(device.get("serial") or ""),
        "faceplate": face,
        "issues": [],
        "checks": [{
            "id": "c6",
            "name": "Approved in NetBox",
            "result": "fail",
            "detail": "This device is in Netdisco and not in NetBox",
        }],
        "hardware": [],
        "checkRunAt": _clock_stamp(now),
        "interfaces": [
            {
                "name": port.get("name") or "",
                "type": port.get("type") or "",
                "enabled": port.get("state") != "disabled",
                "mac": "",
                "description": "",
            }
            for port in ports
        ],
        "addresses": [],
        "neighbors": snap.get("neighbors") or [],
        "backup": {"available": False, "reason": "This device is in Netdisco only", "status": "", "at": "", "config": ""},
        "history": [],
        "sources": [
            {"name": "netbox", "ok": False, "detail": "Not in NetBox"},
            {"name": "prometheus", "ok": False, "detail": "No NetBox device to query"},
            {"name": "alertmanager", "ok": True, "detail": ""},
            {"name": "oxidized", "ok": False, "detail": "This device is in Netdisco only"},
            {"name": "netdisco", "ok": True, "detail": ""},
        ],
        "comparison": comparison,
    }


def _faceplate(form: str, role: str, hostname: str, model: str, ports: list[dict], identity: dict | None = None) -> dict:
    ident = identity or {}
    model_name = str(ident.get("model") or model or "")
    base = {
        "form_factor": form if form in FORM_FACTORS else "generic",
        "role": role,
        "hostname": hostname,
        "model": model_name,
        "modelName": model_name,
        "partNumber": str(ident.get("part_number") or ""),
        "slug": str(ident.get("slug") or ""),
        "manufacturer": str(ident.get("manufacturer") or ""),
    }
    if form == "switch-stack":
        groups: dict[int, list] = {}
        for port in ports:
            match = _MEMBER_RE.match(port["name"])
            number = int(match.group(1)) if match else 1
            groups.setdefault(number, []).append(port)
        members = []
        for number in sorted(groups):
            members.append({
                "id": "m%s" % number,
                "number": number,
                "health": _member_health(groups[number]),
                "note": _member_health(groups[number]).capitalize(),
                "ports": groups[number],
            })
        base["members"] = members
        return base
    if form == "modular-chassis":
        state = "up"
        if any(port["state"] == "fault" for port in ports):
            state = "fault"
        elif any(port["state"] == "warning" for port in ports):
            state = "warning"
        base["modules"] = [{
            "id": "slot-1",
            "kind": "linecard",
            "slot": "1",
            "label": model or "Interfaces",
            "state": state,
            "ports": ports,
        }]
        return base
    base["ports"] = ports
    if form == "ceiling-ap":
        base["radios"] = []
        # No ethernet ports is normal. Offline is a telemetry result, not an empty port list.
        base["apState"] = "unknown"
    return base


def _empty_detail(form_key: str, now: datetime) -> dict:
    form = "firewall" if form_key.startswith(("fg-", "pa-")) else form_key
    if form not in FORM_FACTORS:
        form = "generic"
    display, _mapped = {
        "access-switch-24": ("Access switch", form),
        "access-switch-48": ("Access switch", form),
        "switch-stack": ("Switch stack", form),
        "ceiling-ap": ("Access point", form),
        "wireless-controller": ("Wireless controller", form),
        "firewall": ("Firewall", form),
        "branch-router": ("Branch router", form),
        "modular-chassis": ("Modular chassis", form),
    }.get(form, ("Unclassified", form))
    faceplate = _faceplate(form, display, "—", "", [])
    return {
        "id": form_key,
        "hostname": "—",
        "role": display,
        "site": "—",
        "siteId": "",
        "mgmtIp": "—",
        "modelFamily": "—",
        "health": "unreachable",
        "uptime": "—",
        "lastPoll": "—",
        "firmware": "—",
        "serialMasked": "—",
        "faceplate": faceplate,
        "issues": [],
        "checks": [],
        "hardware": [],
        "checkRunAt": _clock_stamp(now),
    }


def _hw_status(kind: str, value: float | None):
    if value is None:
        return "ok", "—"
    if kind == "cpu":
        status = "fail" if value >= 95 else "warn" if value >= 80 else "ok"
        return status, "%.0f%%" % value
    if kind == "memory":
        status = "fail" if value >= 95 else "warn" if value >= 85 else "ok"
        return status, "%.0f%%" % value
    if kind == "temp":
        status = "fail" if value >= 75 else "warn" if value >= 60 else "ok"
        return status, "%.0f°C" % value
    return "ok", "—"


def _env_state(sample: dict, label_key: str):
    metric = sample.get("metric") or {}
    label = _enum_label(metric, label_key)
    if label:
        return label
    value = _sample_value(sample)
    return {
        1: "normal", 2: "warning", 3: "critical", 4: "shutdown", 5: "notPresent", 6: "notFunctioning",
    }.get(int(value) if value is not None else -1, "")


def _checks_and_hardware(row: dict, bundle: dict, now: datetime):
    reachable = row["health"] != "unreachable"
    fresh = row.get("last_age", 10**12) <= 120
    rtt = bundle.get("rtt")
    if rtt is not None:
        reach_detail = "ICMP round trip %.1f ms" % (float(rtt) * 1000)
    elif reachable:
        reach_detail = "ICMP or SNMP is answering"
    else:
        reach_detail = "No recent ICMP or SNMP sample"
    checks = [
        {"id": "c1", "name": "Reachable via SNMP and ICMP", "result": "pass" if reachable else "fail", "detail": reach_detail},
        {"id": "c2", "name": "Telemetry freshness (< 120s)", "result": "pass" if fresh else "warn", "detail": "Last poll %s" % row["lastPoll"]},
        {
            "id": "c3",
            "name": "Port error rate below threshold",
            "result": "fail" if row["portsFault"] else "warn" if row["portsWarn"] else "pass",
            "detail": "%d ports warning, %d ports fault" % (row["portsWarn"], row["portsFault"]),
        },
        {"id": "c6", "name": "Approved in NetBox", "result": "pass", "detail": "Device is present in NetBox"},
    ]
    firmware = row["_device"].get("platform") or ""
    checks.append({
        "id": "c7",
        "name": "Firmware recorded",
        "result": "pass" if firmware else "warn",
        "detail": firmware or "No platform or firmware recorded in NetBox",
    })
    hardware = []
    show_env = not _basic_switch(row)
    psus = [_env_state(sample, "ciscoEnvMonSupplyState") for sample in bundle.get("psus") or []] if show_env else []
    psus = [state for state in psus if state and state != "notPresent"]
    if psus:
        bad = [state for state in psus if state in ("critical", "shutdown", "notFunctioning")]
        warn = [state for state in psus if state == "warning"]
        status = "fail" if bad else "warn" if warn else "ok"
        ok_count = len(psus) - len(bad) - len(warn)
        hardware.append({
            "id": "h1", "name": "Power supplies", "kind": "power", "status": status,
            "value": "%d of %d OK" % (ok_count, len(psus)),
            "detail": "States: %s" % ", ".join(psus),
        })
        checks.append({
            "id": "c4", "name": "Power supplies redundant",
            "result": "fail" if bad else "warn" if warn else "pass",
            "detail": "%d supply samples, %d failed" % (len(psus), len(bad)),
        })
    fans = [_env_state(sample, "ciscoEnvMonFanState") for sample in bundle.get("fans") or []] if show_env else []
    fans = [state for state in fans if state and state != "notPresent"]
    if fans:
        bad = [state for state in fans if state in ("critical", "shutdown", "notFunctioning")]
        warn = [state for state in fans if state == "warning"]
        status = "fail" if bad else "warn" if warn else "ok"
        hardware.append({
            "id": "h2", "name": "Fans", "kind": "fan", "status": status,
            "value": "All normal" if status == "ok" else "%d degraded" % (len(bad) + len(warn)),
            "detail": "States: %s" % ", ".join(fans),
        })
    cpu_status, cpu_value = _hw_status("cpu", bundle.get("cpu"))
    if bundle.get("cpu") is not None:
        hardware.append({"id": "h4", "name": "CPU load", "kind": "cpu", "status": cpu_status, "value": cpu_value, "detail": "5 minute average"})
    mem_status, mem_value = _hw_status("memory", bundle.get("mem"))
    if bundle.get("mem") is not None:
        hardware.append({"id": "h5", "name": "Memory", "kind": "memory", "status": mem_status, "value": mem_value, "detail": "Used percent"})
    temp_status, temp_value = _hw_status("temp", bundle.get("temp"))
    if show_env and bundle.get("temp") is not None:
        hardware.append({"id": "h3", "name": "Temperature", "kind": "temp", "status": temp_status, "value": temp_value, "detail": "Highest sensor"})
    if show_env and (fans or bundle.get("temp") is not None):
        fan_result = "pass"
        if any(item["status"] == "fail" for item in hardware if item["kind"] in ("fan", "temp")):
            fan_result = "fail"
        elif any(item["status"] == "warn" for item in hardware if item["kind"] in ("fan", "temp")):
            fan_result = "warn"
        checks.append({"id": "c5", "name": "Fans and temperature in range", "result": fan_result, "detail": "From SNMP environment tables"})
    return checks, hardware


def _issue_from_alert(alert: dict, index: int) -> dict:
    severity = alert["severity"] if alert["severity"] in ("critical", "warning", "info") else "warning"
    return {
        "id": alert["id"] or ("issue-%s" % index),
        "severity": severity,
        "title": alert["title"],
        "detail": alert["detail"],
        "since": format_ago(alert["ageMinutes"] * 60),
        "target": alert["deviceHostname"] or alert["site"] or "device",
    }


def _severity(raw: str) -> str:
    value = (raw or "").strip().lower()
    if value in ("critical", "error", "page", "major", "high"):
        return "critical"
    if value in ("info", "information", "none", "low"):
        return "info"
    return "warning"


def _matchers(labels: dict) -> list[dict]:
    matchers = []
    for name, value in labels.items():
        if value is None or str(value) == "" or not str(name).strip():
            continue
        matchers.append({"name": str(name), "value": str(value), "isRegex": False, "isEqual": True})
        if len(matchers) >= 30:
            break
    if not matchers:
        matchers.append({"name": "alertname", "value": "unknown", "isRegex": False, "isEqual": True})
    return matchers


def _series(inbound: dict, outbound: dict, errors: dict, window: int, keys: tuple[str, str, str]) -> list[dict]:
    stamps = sorted(set(inbound) | set(outbound) | set(errors))
    points = []
    for ts in stamps:
        points.append({
            "t": int(ts * 1000),
            "label": _label_for(ts, window),
            keys[0]: _round(inbound.get(ts)),
            keys[1]: _round(outbound.get(ts)),
            keys[2]: _round(errors.get(ts)),
            "util": None,
        })
    return points


def _port_matcher(selector: str, port_id: str) -> str:
    port = unquote(port_id or "").replace("~", "/")
    if selector.startswith("{") and selector.endswith("}"):
        inner = selector[1:-1]
    else:
        inner = ""
    pieces = [part for part in (inner,) if part]
    escaped = prom_escape(port)
    if port.isdigit():
        pieces.append('ifIndex="%s"' % escaped)
    else:
        pieces.append('ifName="%s"' % escaped)
    return "{" + ",".join(pieces) + "}"


def _metric_number(sample: dict):
    return _sample_value(sample)


def _posted_ap(raw: dict, known: list[dict]) -> dict:
    name = str(raw.get("name") or "").strip()
    wlc = str(raw.get("wlc") or "").strip().lower()
    found = None
    for row in known or []:
        if str(row.get("name") or "").lower() != name.lower():
            continue
        if wlc and wlc not in str(row.get("wlc") or "").lower():
            continue
        found = row
        break
    ap = dict(found or {})
    for key in ("name", "wlc", "model", "serial", "ip", "ios", "location", "siteTag", "mac"):
        if raw.get(key):
            ap[key] = raw.get(key)
    ap["name"] = name
    if not ap.get("ios") and raw.get("sw_version"):
        ap["ios"] = raw.get("sw_version")
    return ap


def _annotate_access_points(rows: list[dict], devices: list[dict]) -> None:
    sites = []
    seen = set()
    for device in devices or []:
        name = str(device.get("site_name") or device.get("site") or "").strip()
        slug = str(device.get("site_slug") or "").strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            sites.append({"name": name, "slug": slug})
    for row in rows or []:
        match = match_access_point(devices, row)
        row["inNetbox"] = match is not None
        row["netboxId"] = str(match.get("id") or "") if match else ""
        if match and not row.get("netboxSite"):
            row["netboxSite"] = str(match.get("site_name") or match.get("site") or "")
        row["suggestedSite"] = suggest_ap_site(row, sites)


def attach_netbox_sites(rows: list[dict], devices: list[dict]) -> list[dict]:
    """Match an AP name, then its CDP switch, to a NetBox device site."""
    by_name = {}
    for device in devices or []:
        label = str(device.get("name") or device.get("hostname") or "").strip().lower()
        site = str(device.get("site_name") or device.get("site") or "")
        if label and site:
            by_name[label] = site
    for row in rows or []:
        ap = str(row.get("name") or "").strip().lower()
        switch = str(row.get("neighborSwitch") or "").strip().lower()
        site = by_name.get(ap) or by_name.get(switch) or ""
        row["netboxSite"] = site
        if site:
            row["site"] = site
    return rows


def events_from_range(result: list[dict], what: str) -> list[dict]:
    events = []
    for series in result or []:
        metric = series.get("metric") or {}
        previous = None
        for pair in series.get("values") or []:
            try:
                stamp = int(float(pair[0]))
                value = pair[1]
            except (TypeError, ValueError, IndexError):
                continue
            if previous is None:
                previous = value
                continue
            if str(value) != str(previous):
                events.append({
                    "t": stamp,
                    "what": what,
                    "ap": str(metric.get("ap") or metric.get("ap_name") or ""),
                    "radio": str(metric.get("radio") or metric.get("slot") or ""),
                    "from": previous,
                    "to": value,
                })
                previous = value
    return events


def mount_fleet(app, user_of) -> None:
    def fleet() -> FleetService:
        service = getattr(app.state, "fleet", None)
        if service is None:
            service = FleetService(app.state.settings)
            app.state.fleet = service
        return service

    def reader(request: Request):
        user, _csrf = user_of(request)
        return user

    @app.get("/api/v1/health")
    def api_health(request: Request):
        reader(request)
        return fleet().health()

    @app.get("/api/v1/summary")
    def summary(request: Request):
        reader(request)
        return fleet().summary()

    @app.get("/api/v1/access-points/detail")
    def access_point_detail(request: Request):
        reader(request)
        params = request.query_params
        return fleet().access_point_detail(params.get("wlc") or "", params.get("name") or "")

    @app.get("/api/v1/access-points")
    def access_points(request: Request):
        reader(request)
        params = request.query_params
        return fleet().list_access_points(
            page=_qint(params.get("page"), 1, 1, 100000),
            page_size=_qint(params.get("page_size"), 50, 1, 100),
            q=(params.get("q") or "")[:200],
            wlc=(params.get("wlc") or "")[:200],
            site=(params.get("site") or "")[:200],
            status=(params.get("status") or "")[:40],
        )

    @app.get("/api/v1/devices")
    def devices(request: Request):
        reader(request)
        params = request.query_params
        page = _qint(params.get("page"), 1, 1, 100000)
        page_size = _qint(params.get("page_size"), 25, 1, 200)
        sort = params.get("sort") or "hostname:asc"
        return fleet().list_devices(
            page=page, page_size=page_size, q=(params.get("q") or "")[:200],
            health=(params.get("health") or "all")[:40], role=(params.get("role") or "all")[:80], sort=sort[:80],
        )

    @app.get("/api/v1/devices/ports/{port_id}/metrics")
    def port_metrics_legacy(port_id: str, request: Request):
        reader(request)
        params = request.query_params
        range_key = params.get("range") or "24h"
        custom = _qint(params.get("custom_min"), 180, 1, 10080)
        return fleet().metrics(None, "port", range_key, custom, port_id)

    @app.get("/api/v1/devices/{device_id}")
    def device_one(device_id: str, request: Request):
        reader(request)
        return fleet().get_device(device_id)

    @app.post("/api/v1/devices/{device_id}/netbox-sync")
    def netbox_sync(device_id: str, request: Request):
        user = reader(request)
        from .auth import can_operate
        if not can_operate(user.role):
            raise ApiError(403, "forbidden", "your role cannot change devices, alerts, or NetBridge")
        try:
            result = fleet().sync_netbox_inventory(device_id)
        except ApiError as exc:
            _record_netbox_sync(request, user, "failed", exc.code)
            raise
        written = ",".join(result.get("updated") or []) or "unchanged"
        _record_netbox_sync(request, user, "ok", "%s %s" % (result.get("hostname") or device_id, written))
        return result

    @app.get("/api/v1/devices/{device_id}/metrics/throughput")
    def throughput(device_id: str, request: Request):
        reader(request)
        params = request.query_params
        return fleet().metrics(device_id, "throughput", params.get("range") or "24h", _qint(params.get("custom_min"), 180, 1, 10080))

    @app.get("/api/v1/devices/{device_id}/metrics/resources")
    def resources(device_id: str, request: Request):
        reader(request)
        params = request.query_params
        return fleet().metrics(device_id, "resources", params.get("range") or "24h", _qint(params.get("custom_min"), 180, 1, 10080))

    @app.get("/api/v1/devices/{device_id}/ports/top")
    def top_ports(device_id: str, request: Request):
        reader(request)
        metric = request.query_params.get("metric") or "util"
        if metric != "util":
            raise ApiError(400, "bad_query", "metric must be util")
        return fleet().metrics(device_id, "top", request.query_params.get("range") or "24h", 180)

    @app.get("/api/v1/devices/{device_id}/ports/{port_id}/metrics")
    def port_metrics(device_id: str, port_id: str, request: Request):
        reader(request)
        params = request.query_params
        return fleet().metrics(device_id, "port", params.get("range") or "24h", _qint(params.get("custom_min"), 180, 1, 10080), port_id)

    @app.get("/api/v1/sites")
    def sites(request: Request):
        reader(request)
        params = request.query_params
        return fleet().list_sites(
            page=_qint(params.get("page"), 1, 1, 100000),
            page_size=_qint(params.get("page_size"), 25, 1, 200),
            q=(params.get("q") or "")[:200],
            health=(params.get("health") or "all")[:40],
            region=(params.get("region") or "all")[:80],
        )

    @app.get("/api/v1/sites/{site_id}/devices")
    def site_devices(site_id: str, request: Request):
        reader(request)
        return fleet().site_devices(site_id)

    @app.get("/api/v1/alerts")
    def alerts(request: Request):
        reader(request)
        params = request.query_params
        return fleet().list_alerts(
            status=(params.get("status") or "")[:40],
            severity=(params.get("severity") or "")[:40],
            site=(params.get("site") or "")[:80],
        )

    @app.post("/api/v1/alerts/acknowledge")
    async def acknowledge(request: Request):
        user = reader(request)
        from .auth import can_operate
        if not can_operate(user.role):
            raise ApiError(403, "forbidden", "your role cannot acknowledge alerts")
        try:
            body = await request.json()
        except Exception:
            raise ApiError(400, "bad_body", "body must be JSON")
        if not isinstance(body, dict):
            raise ApiError(400, "bad_body", "body must be a JSON object")
        return fleet().acknowledge(body.get("ids"), getattr(user, "email", "") or "")

    @app.post("/api/v1/alerts/webhook")
    async def webhook(request: Request):
        try:
            body = await request.json()
        except Exception:
            raise ApiError(400, "bad_body", "body must be JSON")
        return fleet().accept_webhook(body, request.headers.get("authorization", ""))
