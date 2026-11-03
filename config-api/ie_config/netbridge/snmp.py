"""Walk Cisco WLC access-point tables.

AireOS uses AIRESPACE-WIRELESS-MIB bsnAPTable. Catalyst 9800 uses
CISCO-LWAPP-AP-MIB cLApName plus the same AireOS table when the controller
still serves it. CDP neighbours come from CISCO-LWAPP-CDP-MIB. GetBulk keeps
a controller with thousands of APs to a few hundred UDP exchanges.
"""

from __future__ import annotations

import socket

from .ber import END_OF_MIB, decode_message, enc_int, enc_ip, enc_str, encode_getbulk, oid_tuple, under

# bsnAPEntry columns. Index is the AP Ethernet MAC.
AIRE_NAME = "1.3.6.1.4.1.14179.2.2.1.1.3"
AIRE_MODEL = "1.3.6.1.4.1.14179.2.2.1.1.16"
AIRE_SERIAL = "1.3.6.1.4.1.14179.2.2.1.1.17"
AIRE_IP = "1.3.6.1.4.1.14179.2.2.1.1.19"
# cLApName, indexed by radio MAC.
XE_NAME = "1.3.6.1.4.1.9.9.513.1.1.1.1.5"
# clcCdpApCacheEntry: AP name, neighbour name, neighbour port.
CDP_AP = "1.3.6.1.4.1.9.9.623.1.3.1.1.2"
CDP_NEIGH = "1.3.6.1.4.1.9.9.623.1.3.1.1.6"
CDP_PORT = "1.3.6.1.4.1.9.9.623.1.3.1.1.9"

ROW_CAP = 20000


def udp_exchange(host: str, port: int, packet: bytes, timeout: float) -> bytes:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout)
        sock.sendto(packet, (host, int(port)))
        data, _addr = sock.recvfrom(65535)
        return data
    finally:
        sock.close()


def walk(host: str, port: int, community: str, base: str, *, max_reps: int = 20, timeout: float = 3.0, limit: int = ROW_CAP, exchange=None) -> list[tuple[str, object]]:
    """Walk one column. Stops at endOfMibView, a foreign OID, or ``limit`` rows."""
    send = exchange or udp_exchange
    rows: list[tuple[str, object]] = []
    current = base
    seen = set()
    request_id = 1
    reps = max(1, min(50, int(max_reps)))
    while len(rows) < limit:
        packet = encode_getbulk(community, current, request_id, reps)
        request_id += 1
        try:
            raw = send(host, port, packet, timeout)
        except (OSError, TimeoutError):
            if reps > 5 and not rows:
                reps = 5
                continue
            break
        try:
            decoded = decode_message(raw)
        except ValueError:
            if reps > 5:
                reps = 5
                continue
            break
        if decoded.get("error"):
            break
        binds = decoded.get("binds") or []
        if not binds:
            break
        advanced = False
        stop = False
        for oid, value in binds:
            if not isinstance(oid, str) or not under(oid, base) or oid == base:
                stop = True
                break
            if value is END_OF_MIB:
                stop = True
                break
            if oid in seen or oid_tuple(oid) <= oid_tuple(current):
                stop = True
                break
            seen.add(oid)
            rows.append((oid, value))
            current = oid
            advanced = True
            if len(rows) >= limit:
                break
        if stop or not advanced:
            break
    return rows


def _suffix(oid: str, base: str) -> str:
    if oid.startswith(base + "."):
        return oid[len(base) + 1:]
    return ""


def _column(rows: list[tuple[str, object]], base: str) -> dict[str, str]:
    out = {}
    for oid, value in rows:
        key = _suffix(oid, base)
        if not key or value is None or value is END_OF_MIB:
            continue
        out[key] = str(value).strip()
    return out


def _text_ip(value: str) -> str:
    text = (value or "").strip()
    if text.count(".") == 3:
        parts = text.split(".")
        if all(part.isdigit() and 0 <= int(part) <= 255 for part in parts):
            return text
    return text


def join_aireos(columns: dict[str, dict[str, str]]) -> list[dict]:
    names = columns.get("name") or {}
    aps = []
    for index, name in names.items():
        if not name:
            continue
        aps.append({
            "index": index,
            "name": name,
            "model": (columns.get("model") or {}).get(index, ""),
            "serial": (columns.get("serial") or {}).get(index, ""),
            "ip": _text_ip((columns.get("ip") or {}).get(index, "")),
            "platform": "aireos",
        })
    return aps


def join_xe_names(names: dict[str, str]) -> list[dict]:
    aps = []
    for index, name in names.items():
        if not name:
            continue
        aps.append({
            "index": index,
            "name": name,
            "model": "",
            "serial": "",
            "ip": "",
            "platform": "ios-xe",
        })
    return aps


def apply_cdp(aps: list[dict], cdp_name: dict[str, str], cdp_neigh: dict[str, str], cdp_port: dict[str, str]) -> None:
    by_name = {}
    for index, name in cdp_name.items():
        key = name.strip().lower()
        if not key:
            continue
        by_name[key] = (
            cdp_neigh.get(index, ""),
            cdp_port.get(index, ""),
        )
    for ap in aps:
        neigh, port = by_name.get(ap["name"].strip().lower(), ("", ""))
        ap["neighbor"] = neigh
        ap["neighbor_port"] = port


def merge_aps(aire: list[dict], xe: list[dict]) -> tuple[list[dict], str]:
    """Prefer a row that has a serial. 9800 often fills both tables."""
    by_name: dict[str, dict] = {}
    for ap in aire + xe:
        key = ap["name"].strip().lower()
        if not key:
            continue
        current = by_name.get(key)
        if current is None:
            by_name[key] = dict(ap)
            continue
        for field in ("model", "serial", "ip", "neighbor", "neighbor_port"):
            if not current.get(field) and ap.get(field):
                current[field] = ap[field]
        if ap.get("platform") == "ios-xe":
            current["platform"] = "ios-xe"
    platform = "ios-xe" if xe else ("aireos" if aire else "")
    return list(by_name.values()), platform


def scan_wlc(host: str, port: int, community: str, *, exchange=None, limit: int = ROW_CAP, timeout: float = 3.0) -> dict:
    if not community or community == "unset-placeholder":
        return {"ok": False, "message": "SNMPv2c community is not configured for this controller", "aps": [], "platform": ""}
    kwargs = {"exchange": exchange, "limit": limit, "timeout": timeout}
    aire_name = _column(walk(host, port, community, AIRE_NAME, **kwargs), AIRE_NAME)
    aire_model = _column(walk(host, port, community, AIRE_MODEL, **kwargs), AIRE_MODEL) if aire_name else {}
    aire_serial = _column(walk(host, port, community, AIRE_SERIAL, **kwargs), AIRE_SERIAL) if aire_name else {}
    aire_ip = _column(walk(host, port, community, AIRE_IP, **kwargs), AIRE_IP) if aire_name else {}
    xe_name = _column(walk(host, port, community, XE_NAME, **kwargs), XE_NAME)
    cdp_ap = _column(walk(host, port, community, CDP_AP, **kwargs), CDP_AP)
    cdp_neigh = _column(walk(host, port, community, CDP_NEIGH, **kwargs), CDP_NEIGH) if cdp_ap else {}
    cdp_port = _column(walk(host, port, community, CDP_PORT, **kwargs), CDP_PORT) if cdp_ap else {}
    aire = join_aireos({"name": aire_name, "model": aire_model, "serial": aire_serial, "ip": aire_ip})
    xe = join_xe_names(xe_name)
    aps, platform = merge_aps(aire, xe)
    apply_cdp(aps, cdp_ap, cdp_neigh, cdp_port)
    if not aps:
        return {"ok": False, "message": "No access points answered on %s" % host, "aps": [], "platform": platform}
    capped = len(aire_name) >= limit or len(xe_name) >= limit
    return {
        "ok": True,
        "message": "walk stopped at %d rows" % limit if capped else "",
        "aps": aps,
        "platform": platform,
        "capped": capped,
    }


def value_for(kind: str, value: str) -> bytes:
    """Encode a simulated column value. Used by the in-process agent."""
    if kind == "ip":
        return enc_ip(value)
    if kind == "int":
        return enc_int(int(value))
    return enc_str(value)
