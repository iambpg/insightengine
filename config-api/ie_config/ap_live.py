"""Read-only live access-point lookup over SSH.

A page open asks the wireless controller that owns the AP. Nothing here polls
in the background. Commands are fixed strings; the only inserted text is an
AP name that matches a short allowlist. Credentials are never logged.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from .ap_status import canon_mac
from .device_cli import PLATFORMS, ParamikoRunner, _load_credentials
from .device_logins import credential_for, load_store
from .errors import ApiError
from .hostnames import names_match

log = logging.getLogger("ie-config.ap-live")

_AP_NAME = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_IP = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")
_SUMMARY_LIMIT = 2_000_000
_RAW_LIMIT = 20 * 1024
_SUCCESS_TTL = 60
_MISS_TTL = 60
_OWNER_TTL = 3600
_HINT_KEYS = {
    "wlc", "controller", "wireless_controller", "wlc_name", "controller_name",
    "primary_controller", "primary_wlc", "cdp_neighbor", "cdp_neighbour",
    "neighbor", "neighbour", "neighbor_switch", "neighbour_switch",
}

_GATE = None
_GATE_LOCK = threading.Lock()
_INFLIGHT: dict[str, dict] = {}
_INFLIGHT_GUARD = threading.Lock()


def platform_kind(platform: str, role: str = "", device_type: str = "") -> str:
    """Same rule as config/telegraf/wlc/render_wlc.py platform_kind."""
    text = "%s %s %s" % (platform or "", role or "", device_type or "")
    text = text.lower()
    if "ios-xe" in text or "iosxe" in text or "9800" in text:
        return "iosxe"
    return "aireos"


def validate_ap_name(name: str) -> str:
    text = (name or "").strip()
    if not text or text.startswith("-") or not _AP_NAME.match(text):
        raise ApiError(
            400,
            "bad_ap_name",
            "Access point name may only contain letters, numbers, dots, underscores, colons and hyphens, and must be at most 64 characters.",
        )
    return text


def classify_key(key: str) -> tuple[str, str]:
    text = (key or "").strip()
    mac = canon_mac(text)
    if mac:
        return "mac", mac
    if _IP.match(text):
        return "ip", text
    if text and not text.startswith("-") and _AP_NAME.match(text):
        return "name", text
    raise ApiError(
        400,
        "bad_ap_name",
        "Access point name may only contain letters, numbers, dots, underscores, colons and hyphens, and must be at most 64 characters.",
    )


def _blank() -> dict:
    return {
        "name": None,
        "mac": None,
        "ip": None,
        "model": None,
        "serial": None,
        "ios": None,
        "mode": None,
        "adminState": None,
        "operState": None,
        "uptime": None,
        "joinTime": None,
        "location": None,
        "country": None,
        "primaryController": None,
        "secondaryController": None,
        "siteTag": None,
        "policyTag": None,
        "rfTag": None,
        "apGroup": None,
        "flexGroup": None,
        "power": None,
        "cdpSwitch": None,
        "cdpPort": None,
        "radios": [],
    }


_SCALAR = {
    "cisco ap name": "name",
    "ap name": "name",
    "mac address": "mac",
    "ethernet mac address": "mac",
    "ip address": "ip",
    "ap model": "model",
    "ap serial number": "serial",
    "ios version": "ios",
    "software version": "ios",
    "ap mode": "mode",
    "administrative state": "adminState",
    "operation state": "operState",
    "ap up time": "uptime",
    "ap join date and time": "joinTime",
    "join date and time": "joinTime",
    "cisco ap location": "location",
    "ap location": "location",
    "country code": "country",
    "ap country code": "country",
    "primary cisco controller name": "primaryController",
    "primary cisco switch name": "primaryController",
    "secondary cisco controller name": "secondaryController",
    "secondary cisco switch name": "secondaryController",
    "site tag name": "siteTag",
    "policy tag name": "policyTag",
    "rf tag name": "rfTag",
    "ap group name": "apGroup",
    "cisco ap group name": "apGroup",
    "flexconnect group": "flexGroup",
    "flexconnect group name": "flexGroup",
    "power type/mode": "power",
}


def _norm_key(label: str) -> str:
    return " ".join((label or "").strip().lower().split())


def _split_field(line: str) -> tuple[str, str] | None:
    text = (line or "").strip()
    if not text or set(text) <= {"-", "="}:
        return None
    if "...." in text:
        left, right = re.split(r"\.{2,}", text, maxsplit=1)
        if left.strip():
            return left.strip(), right.strip()
    match = re.match(r"^(.*?)\s+:\s*(.*)$", text)
    if match and match.group(1).strip():
        return match.group(1).strip(), match.group(2).strip()
    return None


def _apply_scalar(body: dict, radio: dict | None, label: str, value: str) -> None:
    key = _norm_key(label)
    if not value:
        return
    if radio is not None:
        if key == "administrative state":
            radio["admin"] = value
            return
        if key == "operation state":
            radio["oper"] = value
            return
        if key == "current channel":
            radio["channel"] = value
            return
        if key in ("tx power", "current tx power level") and (not radio.get("txPower") or "dbm" in value.lower()):
            radio["txPower"] = value
            return
        return
    field = _SCALAR.get(key)
    if field:
        body[field] = value


def _finish(body: dict) -> dict:
    if body.get("mac"):
        body["mac"] = canon_mac(str(body["mac"])) or str(body["mac"])
    for radio in body["radios"]:
        for field in ("admin", "oper", "channel", "txPower"):
            radio.setdefault(field, None)
    return body


def _parse_general(text: str) -> dict:
    body = _blank()
    radio = None
    if not isinstance(text, str):
        return body
    for line in text.splitlines():
        try:
            slot = re.match(r"^\s*radio slot\s+(\d+)\s*$", line, re.I)
            if slot:
                radio = {"slot": slot.group(1), "admin": None, "oper": None, "channel": None, "txPower": None}
                body["radios"].append(radio)
                continue
            pair = _split_field(line)
            if not pair:
                continue
            _apply_scalar(body, radio, pair[0], pair[1])
        except Exception:
            continue
    return _finish(body)


def parse_iosxe_config_general(text: str) -> dict:
    return _parse_general(text)


def parse_aireos_config_general(text: str) -> dict:
    return _parse_general(text)


def parse_cdp_neighbors(text: str) -> dict:
    switch = None
    port = None
    if not isinstance(text, str):
        return {"cdpSwitch": None, "cdpPort": None}
    for line in text.splitlines():
        try:
            pair = _split_field(line)
            if not pair:
                continue
            key = _norm_key(pair[0])
            if key in ("neighbor name", "neighbour name", "device id", "neighbor device"):
                switch = pair[1] or switch
            if key in ("neighbor port", "neighbour port", "port id", "neighbor interface"):
                port = pair[1] or port
        except Exception:
            continue
    if switch or port:
        return {"cdpSwitch": switch, "cdpPort": port}
    for line in text.splitlines():
        try:
            parts = line.split()
            if len(parts) < 3 or "----" in line or "neighbor" in line.lower() or "ap name" in line.lower():
                continue
            if re.search(r"(?i)(gigabit|tengig|ethernet|gi\d|te\d|fa\d|tw\d)", parts[-1]):
                switch = parts[-2]
                port = parts[-1]
        except Exception:
            continue
    return {"cdpSwitch": switch, "cdpPort": port}


def _header_spans(header: str, titles: list[str]) -> list[tuple[str, int]]:
    spans = []
    for title in titles:
        idx = header.find(title)
        if idx >= 0:
            spans.append((title, idx))
    spans.sort(key=lambda item: item[1])
    return spans


def _slice_row(line: str, spans: list[tuple[str, int]]) -> dict:
    out = {}
    for index, (title, start) in enumerate(spans):
        end = spans[index + 1][1] if index + 1 < len(spans) else len(line)
        out[title] = line[start:end].strip() if start < len(line) else ""
    return out


def _parse_summary(text: str, titles: list[str]) -> list[dict]:
    rows = []
    if not isinstance(text, str) or not text.strip():
        return rows
    lines = text.splitlines()
    spans: list[tuple[str, int]] = []
    for line in lines:
        try:
            if "AP Name" in line and "MAC" in line:
                spans = _header_spans(line, titles)
                continue
            if not spans or not line.strip() or set(line.strip()) <= {"-", " "}:
                continue
            fields = _slice_row(line, spans)
            name = fields.get("AP Name") or ""
            if not name or name.lower().startswith("ap name"):
                continue
            mac = canon_mac(fields.get("Ethernet MAC") or "") or (fields.get("Ethernet MAC") or None)
            rows.append({
                "name": name,
                "mac": mac or None,
                "ip": fields.get("IP Address") or None,
                "model": fields.get("AP Model") or None,
                "location": fields.get("Location") or None,
                "country": fields.get("Country") or None,
                "operState": fields.get("State") or None,
                "serial": fields.get("Serial") or None,
            })
        except Exception:
            continue
    return rows


_IOSXE_SUMMARY = ["AP Name", "Slots", "AP Model", "Ethernet MAC", "Radio MAC", "Location", "Country", "IP Address", "State"]
_AIREOS_SUMMARY = ["AP Name", "Slots", "AP Model", "Ethernet MAC", "Location", "Country", "IP Address", "Clients"]


def parse_iosxe_ap_summary(text: str) -> list[dict]:
    return _parse_summary(text, _IOSXE_SUMMARY)


def parse_aireos_ap_summary(text: str) -> list[dict]:
    return _parse_summary(text, _AIREOS_SUMMARY)


def output_missing(text: str, name: str) -> bool:
    low = (text or "").strip().lower()
    if not low:
        return True
    needles = (
        "ap name not found",
        "cisco ap name not found",
        "invalid ap name",
        "ap does not exist",
        "% error: ap name",
    )
    if any(needle in low for needle in needles):
        return True
    if name and ("ap name %s not found" % name.lower()) in low:
        return True
    return False


def is_controller(device: dict) -> bool:
    """Wireless-controller role, using the same order as fleet._role_form."""
    slug = str(device.get("role_slug") or "").strip().lower()
    name = str(device.get("role_name") or device.get("role") or "").strip().lower()
    model = str(device.get("model") or "").lower()
    blob = " ".join((slug, name, model))
    if slug in ("access-point", "access_points", "ap") or "access point" in blob or "access-point" in blob:
        return False
    return "wireless" in blob or slug in ("wlc", "wireless-controller")


def is_access_point(device: dict) -> bool:
    slug = str(device.get("role_slug") or "").strip().lower()
    name = str(device.get("role_name") or device.get("role") or "").strip().lower()
    blob = " ".join((slug, name, str(device.get("model") or "").lower()))
    return slug in ("access-point", "access_points", "ap") or "access point" in blob or "access-point" in blob


def _row_matches(row: dict, key: str, suffixes: list[str]) -> bool:
    text = (key or "").strip()
    low = text.lower()
    mac = canon_mac(text)
    if not text:
        return False
    for field in ("name", "serial", "mac", "ip"):
        value = str(row.get(field) or "")
        if value and value.lower() == low:
            return True
        if field == "mac" and mac and canon_mac(value) == mac:
            return True
        if field == "name" and names_match(value, text, suffixes):
            return True
    return False


def _match_controller(label: str, controllers: list[dict], suffixes: list[str]) -> dict | None:
    text = (label or "").strip()
    if not text:
        return None
    if _IP.match(text):
        for item in controllers:
            if str(item.get("ip") or "") == text:
                return item
        return None
    for item in controllers:
        if names_match(text, str(item.get("name") or ""), suffixes):
            return item
        if str(item.get("ip") or "") == text:
            return item
    return None


def _controller_record(device: dict, source: str) -> dict:
    kind = platform_kind(
        str(device.get("platform") or ""),
        str(device.get("role_name") or device.get("role") or ""),
        str(device.get("model") or ""),
    )
    return {
        "id": str(device.get("id") or ""),
        "name": str(device.get("name") or ""),
        "ip": str(device.get("ip") or ""),
        "platform": kind,
        "site_id": str(device.get("site_id") or ""),
        "site_name": str(device.get("site_name") or ""),
        "source": source,
    }


def _unique(records: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for record in records:
        key = record.get("id") or record.get("name")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(record)
    return out


def resolve_owner_wlc(ap_key: str, *, rows: list[dict], devices: list[dict], suffixes: list[str] | None = None, hint: str = "", last_id: str = "") -> list[dict]:
    """Ordered controllers to try: remembered, hint, metrics label, NetBox, then the rest."""
    suffixes = list(suffixes or [])
    controllers = [device for device in devices if is_controller(device)]
    by_id = {str(device.get("id") or ""): device for device in controllers}
    ordered: list[dict] = []
    matched = next((row for row in rows if isinstance(row, dict) and _row_matches(row, ap_key, suffixes)), None)
    label = ""
    if matched:
        label = str(matched.get("wlc") or matched.get("source") or "").strip()
    metrics = _match_controller(label, controllers, suffixes) if label else None
    if metrics:
        ordered.append(_controller_record(metrics, "metrics"))

    ap_device = next((device for device in devices if is_access_point(device) and _row_matches(device, ap_key, suffixes)), None)
    site_id = str((ap_device or {}).get("site_id") or (matched or {}).get("site_id") or "")
    if ap_device:
        custom = ap_device.get("custom_fields") if isinstance(ap_device.get("custom_fields"), dict) else {}
        for field, value in custom.items():
            if not isinstance(value, str) or not value.strip():
                continue
            token = str(field or "").strip().lower().replace(" ", "_")
            if token in _HINT_KEYS or any(word in token for word in ("wlc", "controller", "neighbor", "neighbour", "cdp")):
                found = _match_controller(value, controllers, suffixes)
                if found:
                    ordered.append(_controller_record(found, "netbox"))
        if site_id:
            for device in controllers:
                if str(device.get("site_id") or "") == site_id:
                    ordered.append(_controller_record(device, "netbox"))

    same_site = []
    other = []
    for device in controllers:
        record = _controller_record(device, "search")
        if site_id and record["site_id"] == site_id:
            same_site.append(record)
        else:
            other.append(record)
    same_site.sort(key=lambda item: item["name"].lower())
    other.sort(key=lambda item: item["name"].lower())
    ordered.extend(same_site)
    ordered.extend(other)
    ordered = _unique(ordered)

    def _move_front(predicate) -> None:
        for index, record in enumerate(list(ordered)):
            if predicate(record):
                ordered.insert(0, ordered.pop(index))
                return

    if last_id:
        _move_front(lambda record: record["id"] == str(last_id))
    if hint:
        hinted = _match_controller(hint, controllers, suffixes)
        if hinted is None:
            hinted = by_id.get(str(hint))
        if hinted is not None:
            _move_front(lambda record: record["id"] == str(hinted.get("id") or ""))
    return ordered


class SshGate:
    """At most four SSH sessions, and one per controller."""

    def __init__(self, wait_seconds: float = 10, global_limit: int = 4):
        self.wait = wait_seconds
        self.global_sem = threading.BoundedSemaphore(global_limit)
        self._locks: dict[str, threading.BoundedSemaphore] = {}
        self._guard = threading.Lock()

    def _wlc(self, wlc_id: str) -> threading.BoundedSemaphore:
        with self._guard:
            lock = self._locks.get(wlc_id)
            if lock is None:
                lock = threading.BoundedSemaphore(1)
                self._locks[wlc_id] = lock
            return lock

    @contextmanager
    def slot(self, wlc_id: str):
        wlc = self._wlc(wlc_id or "unknown")
        start = time.monotonic()
        if not wlc.acquire(timeout=self.wait):
            raise ApiError(503, "busy", "Live AP lookups are busy. Try again.")
        left = self.wait - (time.monotonic() - start)
        if left <= 0 or not self.global_sem.acquire(timeout=left):
            wlc.release()
            raise ApiError(503, "busy", "Live AP lookups are busy. Try again.")
        try:
            yield
        finally:
            self.global_sem.release()
            wlc.release()


def _default_gate() -> SshGate:
    global _GATE
    with _GATE_LOCK:
        if _GATE is None:
            _GATE = SshGate()
        return _GATE


def _scrub(text: str, secret: str) -> str:
    if not text or not secret:
        return text or ""
    return text.replace(secret, "********")


def _commands(kind: str, name: str) -> tuple[str, str]:
    if kind == "aireos":
        return ("show ap config general %s" % name, "show ap cdp neighbors ap-name %s" % name)
    return ("show ap name %s config general" % name, "show ap name %s cdp neighbors" % name)


class LiveLookup:
    def __init__(self, fleet, runner=None, gate: SshGate | None = None, inflight: dict | None = None, wlc_timeout: float = 12, overall: float = 45):
        self.fleet = fleet
        self.runner = runner or ParamikoRunner()
        self.gate = gate or _default_gate()
        self.inflight = inflight if inflight is not None else _INFLIGHT
        self.inflight_guard = threading.Lock() if inflight is not None else _INFLIGHT_GUARD
        self.wlc_timeout = wlc_timeout
        self.overall = overall

    def fetch(self, key: str, hint: str = "", refresh: bool = False, include_raw: bool = False) -> dict:
        kind, value = classify_key(key)
        norm = value.lower()
        cache_key = "ap-live:" + norm
        if not refresh:
            cached = self.fleet.cache.get(cache_key)
            if isinstance(cached, dict):
                return self._public(cached, include_raw, cached_flag=True)
        token = "%s|%s|%s" % (norm, "1" if refresh else "0", (hint or "").strip().lower())
        with self.inflight_guard:
            slot = self.inflight.get(token)
            if slot is None:
                slot = {"event": threading.Event(), "result": None, "error": None}
                self.inflight[token] = slot
                owner = True
            else:
                owner = False
        if not owner:
            if not slot["event"].wait(self.overall):
                raise ApiError(503, "busy", "Live AP lookups are busy. Try again.")
            if slot["error"] is not None:
                raise slot["error"]
            return self._public(slot["result"], include_raw, cached_flag=False)
        try:
            body = self._load(kind, value, hint, refresh, include_raw)
            slot["result"] = body
            return self._public(body, include_raw, cached_flag=False)
        except ApiError as exc:
            slot["error"] = exc
            raise
        finally:
            slot["event"].set()
            with self.inflight_guard:
                if self.inflight.get(token) is slot:
                    self.inflight.pop(token, None)

    def _public(self, body: dict, include_raw: bool, cached_flag: bool) -> dict:
        out = {
            "accessPoint": dict(body.get("accessPoint") or {}),
            "wlc": dict(body.get("wlc") or {}),
            "resolvedBy": body.get("resolvedBy") or "search",
            "fetchedAt": body.get("fetchedAt"),
            "cached": cached_flag,
            "attempts": [dict(row) for row in body.get("attempts") or []],
        }
        radios = (body.get("accessPoint") or {}).get("radios") or []
        out["accessPoint"]["radios"] = [dict(radio) for radio in radios]
        out["attempts"] = _clean_attempts(out["attempts"])
        if include_raw and body.get("raw"):
            out["raw"] = str(body.get("raw") or "")[:_RAW_LIMIT]
        return out

    def _load(self, kind: str, value: str, hint: str, refresh: bool, include_raw: bool) -> dict:
        deadline = time.monotonic() + self.overall
        suffixes = self._suffixes()
        rows = self._rows(value)
        devices = self._devices()
        last = self.fleet.cache.get("ap-live-last:" + value.lower())
        last_id = ""
        if isinstance(last, dict):
            last_id = str(last.get("id") or "")
        candidates = resolve_owner_wlc(
            value,
            rows=rows,
            devices=devices,
            suffixes=suffixes,
            hint=hint,
            last_id=last_id,
        )
        known = self._known_name(kind, value, rows, devices, suffixes)
        attempts = []
        display = known or value
        for record in candidates:
            if time.monotonic() >= deadline:
                break
            if not refresh and self.fleet.cache.get(self._miss_key(value, record["id"])):
                attempts.append(self._attempt(record, "not-found", "ap_not_found_on_wlc", "Access point %s was not found on %s." % (display, record["name"])))
                continue
            username, password = self._credentials(record)
            if not username:
                attempts.append(self._attempt(
                    record,
                    "error",
                    "no_ssh_credentials",
                    "No SSH credentials are saved for %s. Save them in Device CLI for that wireless controller." % (record["name"] or "the wireless controller"),
                ))
                continue
            if not record.get("ip"):
                attempts.append(self._attempt(record, "error", "no_management_ip", "%s has no management IP, so SSH was not attempted." % record["name"]))
                continue
            remaining = deadline - time.monotonic()
            if remaining < 1:
                break
            try:
                with self.gate.slot(record["id"] or record["ip"]):
                    found, parsed, raw = self._query(record, known, kind, value, min(self.wlc_timeout, remaining), username, password)
            except ApiError as exc:
                if exc.code == "busy":
                    attempts.append(self._attempt(record, "error", "busy", "Live AP lookups are busy. Try again."))
                    raise ApiError(503, "busy", "Live AP lookups are busy. Try again.", {"attempts": _clean_attempts(attempts)})
                code, message = self._ssh_error(exc, record)
                attempts.append(self._attempt(record, "error", code, message))
                continue
            if not found or not parsed:
                self.fleet.cache.put(self._miss_key(value, record["id"]), True, ttl=_MISS_TTL)
                attempts.append(self._attempt(record, "not-found", "ap_not_found_on_wlc", "Access point %s was not found on %s." % (display, record["name"])))
                continue
            attempts.append(self._attempt(record, "ok", "", ""))
            cleaned = _scrub(raw, password)
            body = {
                "accessPoint": parsed,
                "wlc": {"id": record["id"], "name": record["name"], "ip": record["ip"], "platform": record["platform"]},
                "resolvedBy": record.get("source") or "search",
                "fetchedAt": datetime.now(timezone.utc).isoformat(),
                "cached": False,
                "attempts": _clean_attempts(attempts),
                "raw": cleaned[:_RAW_LIMIT],
            }
            self.fleet.cache.put("ap-live:" + value.lower(), body, ttl=_SUCCESS_TTL)
            ap_name = str(parsed.get("name") or known or value).lower()
            self.fleet.cache.put("ap-live-last:" + ap_name, {"id": record["id"], "resolvedBy": body["resolvedBy"]}, ttl=_OWNER_TTL)
            if ap_name != value.lower():
                self.fleet.cache.put("ap-live:" + ap_name, body, ttl=_SUCCESS_TTL)
            log.info("live ap %s from %s", parsed.get("name") or value, record["name"])
            return body
        raise self._final(display, attempts)

    def _query(self, record: dict, known: str | None, kind: str, value: str, timeout: float, username: str, password: str):
        platform = record["platform"]
        prep = PLATFORMS["aireos"]["prep"] if platform == "aireos" else PLATFORMS["ios"]["prep"]
        aireos = platform == "aireos"
        name = known
        started = time.monotonic()
        if not name:
            summary = self._summary(record, prep, aireos, username, password, max(1.0, timeout - (time.monotonic() - started)))
            match = self._match_summary(summary, kind, value)
            if not match or not match.get("name"):
                return False, None, ""
            try:
                name = validate_ap_name(str(match["name"]))
            except ApiError:
                return False, None, ""
        else:
            name = validate_ap_name(name)
        general, cdp_command = _commands(platform, name)
        left = max(1.0, timeout - (time.monotonic() - started))
        text = self.runner.run(record["ip"], username, password, prep, general, left, aireos_login=aireos)
        text = _scrub(text or "", password)
        if output_missing(text, name):
            return False, None, text
        parsed = parse_aireos_config_general(text) if aireos else parse_iosxe_config_general(text)
        if not parsed.get("name") and not parsed.get("mac") and not parsed.get("ip") and not parsed.get("model"):
            return False, None, text
        if not parsed.get("name"):
            parsed["name"] = name
        raw = text
        left = timeout - (time.monotonic() - started)
        if left > 1:
            try:
                cdp = self.runner.run(record["ip"], username, password, prep, cdp_command, left, aireos_login=aireos)
                cdp = _scrub(cdp or "", password)
                neighbour = parse_cdp_neighbors(cdp)
                if neighbour.get("cdpSwitch"):
                    parsed["cdpSwitch"] = neighbour["cdpSwitch"]
                if neighbour.get("cdpPort"):
                    parsed["cdpPort"] = neighbour["cdpPort"]
                raw = (text + "\n" + cdp)[:_RAW_LIMIT]
            except ApiError:
                pass
        return True, parsed, raw

    def _summary(self, record, prep, aireos, username, password, timeout):
        cache_key = "ap-live-summary:" + (record["id"] or record["ip"])
        cached = self.fleet.cache.get(cache_key)
        if isinstance(cached, list):
            return cached
        text = self.runner.run(
            record["ip"], username, password, prep, "show ap summary", timeout,
            aireos_login=aireos, limit=_SUMMARY_LIMIT,
        )
        text = _scrub(text or "", password)
        rows = parse_aireos_ap_summary(text) if aireos else parse_iosxe_ap_summary(text)
        self.fleet.cache.put(cache_key, rows, ttl=_SUCCESS_TTL)
        return rows

    def _match_summary(self, rows: list[dict], kind: str, value: str) -> dict | None:
        mac = canon_mac(value) if kind == "mac" else ""
        for row in rows:
            if kind == "mac" and canon_mac(str(row.get("mac") or "")) == mac:
                return row
            if kind == "ip" and str(row.get("ip") or "") == value:
                return row
            if str(row.get("name") or "").lower() == value.lower():
                return row
            if str(row.get("serial") or "").lower() == value.lower():
                return row
        return None

    def _known_name(self, kind, value, rows, devices, suffixes) -> str | None:
        for row in rows:
            if isinstance(row, dict) and _row_matches(row, value, suffixes):
                name = str(row.get("name") or "").strip()
                if name and _AP_NAME.match(name) and not name.startswith("-"):
                    return name
        for device in devices:
            if is_access_point(device) and _row_matches(device, value, suffixes):
                name = str(device.get("name") or "").strip()
                if name and _AP_NAME.match(name) and not name.startswith("-"):
                    return name
        if kind == "name":
            return value
        return None

    def _credentials(self, record: dict) -> tuple[str, str]:
        settings = self.fleet.settings
        if record.get("id"):
            loaded = _load_credentials(settings, record["id"])
            if loaded:
                return loaded
        try:
            store = load_store(settings)
        except Exception:
            log.warning("device login vault could not be read")
            return "", ""
        accounts = [row for row in (store.get("accounts") or []) if isinstance(row, dict)]
        worked = store.get("worked") if isinstance(store.get("worked"), dict) else {}
        found = credential_for(accounts, record.get("name") or "", worked)
        if found:
            return found
        return "", ""

    def _rows(self, key: str) -> list[dict]:
        try:
            row = self.fleet._find_ap(key)
        except Exception:
            log.warning("access point snapshot lookup failed")
            return []
        if isinstance(row, dict):
            return [row]
        return []

    def _devices(self) -> list[dict]:
        try:
            with self.fleet._session() as client:
                return list(self.fleet._devices_raw(client) or [])
        except Exception:
            log.warning("wireless controller inventory could not be read")
            return []

    def _suffixes(self) -> list[str]:
        try:
            return list(self.fleet._suffixes() or [])
        except Exception:
            return []

    def _miss_key(self, value: str, wlc_id: str) -> str:
        return "ap-live-miss:%s:%s" % (value.lower(), wlc_id)

    def _attempt(self, record: dict, result: str, code: str, message: str) -> dict:
        return {
            "wlc": record.get("name") or "",
            "wlcId": record.get("id") or "",
            "result": result,
            "code": code,
            "message": message,
        }

    def _ssh_error(self, exc: ApiError, record: dict) -> tuple[str, str]:
        if exc.code == "wlc_auth_failed":
            return "wlc_auth_failed", "SSH authentication to %s failed. Check the username and password saved for that wireless controller." % record["name"]
        if exc.code in ("wlc_unreachable", "ssh_failed"):
            return "wlc_unreachable", "Could not open SSH to %s (%s). TCP 22 timed out or was refused." % (record["name"], record.get("ip") or "no address")
        return "wlc_unreachable", "Could not open SSH to %s (%s). TCP 22 timed out or was refused." % (record["name"], record.get("ip") or "no address")

    def _final(self, ap_name: str, attempts: list[dict]) -> ApiError:
        public = _clean_attempts(attempts)
        if not attempts:
            return ApiError(404, "ap_not_found", "No wireless controller is available to query for %s." % ap_name, {"attempts": []})
        missed = [row for row in attempts if row["code"] == "ap_not_found_on_wlc"]
        if missed and len(attempts) == 1:
            return ApiError(404, "ap_not_found_on_wlc", missed[0]["message"], {"attempts": public, "wlc": {"id": missed[0].get("wlcId") or "", "name": missed[0]["wlc"]}})
        if missed:
            names = ", ".join(row["wlc"] for row in attempts if row.get("wlc"))
            return ApiError(
                404,
                "ap_not_found",
                "Access point %s was not found on any wireless controller. Searched %d: %s." % (ap_name, len(attempts), names),
                {"attempts": public},
            )
        order = (
            ("wlc_auth_failed", 502),
            ("wlc_unreachable", 502),
            ("no_ssh_credentials", 409),
            ("no_management_ip", 409),
            ("busy", 503),
        )
        for code, status in order:
            hit = next((row for row in attempts if row["code"] == code), None)
            if hit:
                details = {"attempts": public}
                if code == "no_ssh_credentials":
                    details["wlc"] = {"id": hit.get("wlcId") or "", "name": hit["wlc"]}
                return ApiError(status, code, hit["message"], details)
        return ApiError(502, "wlc_unreachable", attempts[-1]["message"], {"attempts": public})


def _clean_attempts(attempts: list[dict]) -> list[dict]:
    cleaned = []
    for row in attempts or []:
        cleaned.append({
            "wlc": row.get("wlc") or "",
            "result": row.get("result") or "",
            "code": row.get("code") or "",
            "message": row.get("message") or "",
        })
    return cleaned


def live_access_point(fleet, key: str, hint: str = "", refresh: bool = False, include_raw: bool = False) -> dict:
    return LiveLookup(fleet).fetch(key, hint=hint, refresh=refresh, include_raw=include_raw)
