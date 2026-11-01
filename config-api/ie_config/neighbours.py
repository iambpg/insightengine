"""CDP and LLDP neighbours from snmp_exporter, merged with Netdisco.

Netdisco stays first. An SNMP neighbour is added only when it is not already
the same device on the same local port.
"""

from __future__ import annotations

import re

from .hostnames import strip_device_label
from .ifnames import canonical_iface, iface_match_keys

_IPV4 = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


def parse_snmp_address(value: str) -> str:
    """Turn an OctetString address label into an IPv4 or IPv6 string when it is one."""
    raw = (value or "").strip()
    if not raw or _IPV4.match(raw):
        return raw
    if raw.lower().startswith("0x"):
        hexed = raw[2:]
    elif re.fullmatch(r"[0-9a-fA-F:.\s]+", raw):
        hexed = re.sub(r"[^0-9a-fA-F]", "", raw)
    else:
        return raw
    if not re.fullmatch(r"[0-9a-fA-F]+", hexed) or len(hexed) not in (8, 32):
        return raw
    try:
        if len(hexed) == 8:
            parts = [int(hexed[i:i + 2], 16) for i in range(0, 8, 2)]
            return ".".join(str(part) for part in parts)
        return ":".join(hexed[i:i + 4] for i in range(0, 32, 4))
    except ValueError:
        return raw


def _metric(sample: dict) -> dict:
    metric = sample.get("metric") if isinstance(sample, dict) else None
    return metric if isinstance(metric, dict) else {}


def _label(metric: dict, *names: str) -> str:
    for name in names:
        value = metric.get(name)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _index_strings(samples, label: str, key_fn) -> dict:
    found = {}
    for sample in samples or []:
        metric = _metric(sample)
        text = _label(metric, label)
        if not text:
            continue
        found[key_fn(metric)] = {"text": text, "metric": metric}
    return found


def _cdp_key(metric: dict) -> tuple[str, str]:
    ifindex = str(metric.get("ifIndex") or metric.get("cdpCacheIfIndex") or "")
    device = str(metric.get("cdpCacheDeviceIndex") or "")
    return ifindex, device


def _lldp_key(metric: dict) -> tuple[str, str, str]:
    return (
        str(metric.get("lldpRemTimeMark") or ""),
        str(metric.get("lldpRemLocalPortNum") or metric.get("ifIndex") or ""),
        str(metric.get("lldpRemIndex") or ""),
    )


def _local_name(ifindex: str, metric: dict, prom_ports: list[dict]) -> str:
    for port in prom_ports or []:
        if ifindex and str(port.get("id") or "") == str(ifindex):
            return str(port.get("name") or "")
    for field in ("ifName", "ifDescr", "ifAlias"):
        if metric.get(field):
            return str(metric[field])
    return ""


def _port_by_name(prom_ports: list[dict], name: str) -> str:
    wanted = iface_match_keys(name)
    if not wanted:
        return ""
    for port in prom_ports or []:
        keys = set()
        for label in [port.get("name"), *(port.get("names") or [])]:
            keys |= iface_match_keys(str(label or ""))
        if keys & wanted:
            return str(port.get("name") or name)
    return name


def neighbors_from_cdp(device_ids, ports, addresses, platforms, prom_ports=None, suffixes=None) -> list[dict]:
    """One neighbour per (ifIndex, cdpCacheDeviceIndex) that has a name or address."""
    suffixes = list(suffixes or [])
    prom_ports = list(prom_ports or [])
    by_id = _index_strings(device_ids, "cdpCacheDeviceId", _cdp_key)
    by_port = _index_strings(ports, "cdpCacheDevicePort", _cdp_key)
    by_addr = _index_strings(addresses, "cdpCacheAddress", _cdp_key)
    keys = set(by_id) | set(by_port) | set(by_addr)
    rows = []
    for key in keys:
        ifindex, _device = key
        remote = strip_device_label((by_id.get(key) or {}).get("text") or "", suffixes)
        remote_port = (by_port.get(key) or {}).get("text") or ""
        remote_ip = parse_snmp_address((by_addr.get(key) or {}).get("text") or "")
        if not remote and not remote_ip:
            continue
        metric = (by_id.get(key) or by_port.get(key) or by_addr.get(key) or {}).get("metric") or {}
        local = _local_name(ifindex, metric, prom_ports)
        rows.append({
            "localPort": local or ifindex,
            "remoteName": remote,
            "remotePort": remote_port,
            "remoteAddress": remote_ip,
            "protocol": "cdp",
            "source": "cdp",
        })
    rows.sort(key=lambda row: (row["localPort"].lower(), row["remoteName"].lower(), row["remoteAddress"]))
    return rows


def _loc_ports(samples) -> dict[str, str]:
    found = {}
    for sample in samples or []:
        metric = _metric(sample)
        number = str(metric.get("lldpLocPortNum") or "")
        name = _label(metric, "lldpLocPortId", "lldpLocPortDesc", "ifName", "ifDescr")
        if number and name:
            found[number] = name
    return found


def neighbors_from_lldp(names, port_ids, port_descs, man_addrs, loc_ports, prom_ports=None, suffixes=None) -> list[dict]:
    """lldpRemTable rows, with lldpRemManAddr when the management-address table is present."""
    suffixes = list(suffixes or [])
    prom_ports = list(prom_ports or [])
    by_name = _index_strings(names, "lldpRemSysName", _lldp_key)
    by_port = _index_strings(port_ids, "lldpRemPortId", _lldp_key)
    by_desc = _index_strings(port_descs, "lldpRemPortDesc", _lldp_key)
    local_names = _loc_ports(loc_ports)
    addrs: dict[tuple, str] = {}
    for sample in man_addrs or []:
        metric = _metric(sample)
        text = parse_snmp_address(_label(metric, "lldpRemManAddr"))
        if not text:
            continue
        addrs.setdefault(_lldp_key(metric), text)
    rows = []
    for key in set(by_name) | set(by_port) | set(addrs):
        _mark, local_num, _index = key
        remote = strip_device_label((by_name.get(key) or {}).get("text") or "", suffixes)
        remote_port = (by_port.get(key) or {}).get("text") or (by_desc.get(key) or {}).get("text") or ""
        remote_ip = addrs.get(key) or ""
        if not remote and not remote_ip:
            continue
        metric = (by_name.get(key) or by_port.get(key) or {}).get("metric") or {}
        local = local_names.get(local_num) or _local_name(local_num, metric, prom_ports)
        if local:
            local = _port_by_name(prom_ports, local) or local
        rows.append({
            "localPort": local or local_num,
            "remoteName": remote,
            "remotePort": remote_port,
            "remoteAddress": remote_ip,
            "protocol": "lldp",
            "source": "lldp",
        })
    rows.sort(key=lambda row: (row["localPort"].lower(), row["remoteName"].lower(), row["remoteAddress"]))
    return rows


def _same_neighbour(left: dict, right: dict) -> bool:
    left_local = canonical_iface(str(left.get("localPort") or ""))
    right_local = canonical_iface(str(right.get("localPort") or ""))
    if left_local and right_local and left_local != right_local:
        return False
    if bool(left_local) != bool(right_local):
        return False
    left_port = canonical_iface(str(left.get("remotePort") or ""))
    right_port = canonical_iface(str(right.get("remotePort") or ""))
    if left_port and right_port and left_port != right_port:
        return False
    left_name = str(left.get("remoteName") or "").strip().lower()
    right_name = str(right.get("remoteName") or "").strip().lower()
    left_ip = str(left.get("remoteAddress") or "").strip().lower()
    right_ip = str(right.get("remoteAddress") or "").strip().lower()
    if left_name and right_name and left_name == right_name:
        return True
    if left_ip and right_ip and left_ip == right_ip:
        return True
    if left_name and left_name == right_ip:
        return True
    if right_name and right_name == left_ip:
        return True
    return False


def merge_neighbors(primary: list[dict] | None, extra: list[dict] | None) -> list[dict]:
    """Keep every Netdisco neighbour. Add SNMP rows that are not already present."""
    merged = []
    for row in primary or []:
        item = dict(row)
        item.setdefault("source", "netdisco")
        if not item.get("protocol"):
            item["protocol"] = item.get("source") or "netdisco"
        merged.append(item)
    for row in extra or []:
        if any(_same_neighbour(row, have) for have in merged):
            continue
        item = dict(row)
        item.setdefault("source", item.get("protocol") or "snmp")
        merged.append(item)
    return merged
