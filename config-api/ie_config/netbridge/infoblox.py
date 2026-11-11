"""Infoblox Grid Master monitoring: WAPI members and SNMP resources.

The WAPI is JSON and HTTP basic auth against the Grid Master. CPU, memory,
disk, and process health come from the same SNMP community used for ISE.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

import httpx

log = logging.getLogger("ie-config.netbridge.infoblox")

MISSING = "Infoblox URL, username, and password are not configured. Add them in Settings → Vault."
REFUSED = (
    "Infoblox refused this account on the WAPI. A login that works in the browser "
    "is not enough. Use an admin with API access on the Grid Master."
)
_VERSIONS = ("v2.13.1", "v2.12", "v2.11", "v2.10", "v2.7")
_BAD_SERVICE = {"FAILED", "WARNING"}
_PROCESS_MARKERS = (
    ("DNS", ("named",)),
    ("DHCP", ("dhcpd",)),
    ("NTP", ("ntpd", "chronyd")),
    ("TFTP", ("tftpd", "in.tftpd")),
    ("Web", ("httpd", "nginx")),
    ("SNMP", ("snmpd",)),
)


def configured(url: str, username: str, password: str) -> bool:
    return bool((url or "").strip() and (username or "").strip() and (password or "").strip())


def probe(url: str, username: str, password: str, http: httpx.Client | None = None) -> dict:
    """Grid name and member count, without SNMP."""
    body = fetch(url, username, password, http=http)
    if not body.get("ok"):
        return body
    return {
        "ok": True,
        "configured": True,
        "message": "Connected. %s, %d members." % (body.get("grid") or "Infoblox", len(body.get("members") or [])),
        "grid": body.get("grid") or "",
        "version": body.get("version") or "",
        "members": [],
    }


def fetch(url: str, username: str, password: str, http: httpx.Client | None = None, community: str = "") -> dict:
    """Grid members from the WAPI, with SNMP filled in when a community is set."""
    if not configured(url, username, password):
        return _empty(False, MISSING)
    client = http or httpx.Client(timeout=30.0, verify=False)
    own = http is None
    try:
        found = _load(client, url.strip().rstrip("/"), username, password)
    finally:
        if own:
            client.close()
    if not found.get("ok"):
        body = _empty(True, found.get("message") or "Infoblox did not answer")
        body["ok"] = False
        return body
    members = found.get("members") or []
    for member in members:
        _fill_snmp(member, community)
    return {
        "ok": True,
        "configured": True,
        "message": "" if members else "Infoblox answered, but no members were listed.",
        "grid": found.get("grid") or "",
        "version": found.get("version") or "",
        "members": members,
    }


def member_detail(url: str, username: str, password: str, hostname: str, http: httpx.Client | None = None, community: str = "") -> dict:
    """One grid member, including the fuller SNMP reading."""
    wanted = (hostname or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", wanted):
        return {"ok": False, "configured": True, "message": "That member is not in this grid.", "grid": "", "version": "", "member": None}
    body = fetch(url, username, password, http=http, community="")
    if not body.get("ok"):
        body["member"] = None
        return body
    match = None
    for member in body.get("members") or []:
        if str(member.get("hostname") or "").lower() == wanted.lower():
            match = member
            break
    if match is None:
        return {
            "ok": False,
            "configured": True,
            "message": "That member is not in this grid.",
            "grid": body.get("grid") or "",
            "version": body.get("version") or "",
            "member": None,
        }
    _fill_snmp(match, community)
    match["cpus"] = []
    match["uptime"] = ""
    match["description"] = ""
    match["load"] = []
    match["filesystems"] = []
    match["memoryParts"] = []
    if community and match.get("ip"):
        try:
            from .ise import _snmp_detail
            extra = _snmp_detail(match["ip"], community)
        except Exception:
            log.warning("infoblox snmp detail failed for %s", match.get("hostname"))
            extra = None
        if extra:
            match.update(extra)
    return {
        "ok": True,
        "configured": True,
        "message": "",
        "grid": body.get("grid") or "",
        "version": body.get("version") or "",
        "member": match,
    }


def _empty(ready: bool, message: str) -> dict:
    return {
        "ok": False,
        "configured": ready,
        "message": message,
        "grid": "",
        "version": "",
        "members": [],
    }


def _bases(url: str) -> list[str]:
    if "/wapi/" in url.lower():
        return [url]
    return ["%s/wapi/%s" % (url, version) for version in _VERSIONS]


def _load(client: httpx.Client, url: str, username: str, password: str) -> dict:
    host = (urlparse(url).hostname or "").lower()
    last = {"ok": False, "message": "Infoblox did not answer"}
    for base in _bases(url):
        grid = _json_get(client, base + "/grid?_return_fields=name", username, password, log_errors=False)
        if grid.get("status") in (401, 403):
            return {"ok": False, "message": REFUSED}
        if not grid.get("ok"):
            last = grid
            continue
        members = _json_get(
            client,
            base + "/member?_return_fields=host_name,platform,service_status,node_info,vip_setting,ipv6_setting,comment",
            username,
            password,
        )
        if members.get("status") in (401, 403):
            return {"ok": False, "message": REFUSED}
        if not members.get("ok"):
            return {"ok": False, "message": members.get("message") or "Infoblox did not return members."}
        version = base.rstrip("/").rsplit("/wapi/", 1)[-1]
        return {
            "ok": True,
            "message": "",
            "grid": _grid_name(grid.get("body")),
            "version": version,
            "members": _members(members.get("body"), host),
        }
    log.warning("infoblox did not answer a supported WAPI version")
    return {"ok": False, "message": last.get("message") or "Infoblox did not answer"}


def _json_get(client: httpx.Client, url: str, username: str, password: str, log_errors: bool = True) -> dict:
    try:
        response = client.get(url, auth=(username, password), headers={"Accept": "application/json"})
    except httpx.HTTPError:
        log.warning("infoblox request failed")
        return {"ok": False, "message": "Infoblox did not answer", "body": None, "status": 0}
    if response.status_code in (401, 403):
        return {"ok": False, "message": REFUSED, "body": None, "status": response.status_code}
    if response.status_code >= 400:
        if log_errors:
            log.warning("infoblox status %s", response.status_code)
        return {"ok": False, "message": "Infoblox returned HTTP %s" % response.status_code, "body": None, "status": response.status_code}
    try:
        body = response.json()
    except ValueError:
        return {"ok": False, "message": "Infoblox did not return JSON.", "body": None, "status": response.status_code}
    return {"ok": True, "message": "", "body": body, "status": response.status_code}


def _rows(body) -> list:
    if isinstance(body, list):
        return [row for row in body if isinstance(row, dict)]
    if isinstance(body, dict):
        result = body.get("result")
        if isinstance(result, list):
            return [row for row in result if isinstance(row, dict)]
        return [body]
    return []


def _grid_name(body) -> str:
    for row in _rows(body):
        name = str(row.get("name") or "").strip()
        if name:
            return name[:128]
    return ""


def _members(body, grid_host: str) -> list[dict]:
    members = []
    for row in _rows(body):
        hostname = str(row.get("host_name") or "").strip()
        if not hostname:
            continue
        vip = row.get("vip_setting") if isinstance(row.get("vip_setting"), dict) else {}
        ipv6 = row.get("ipv6_setting") if isinstance(row.get("ipv6_setting"), dict) else {}
        ip = str(vip.get("address") or ipv6.get("virtual_ip") or "").strip()
        nodes = row.get("node_info") if isinstance(row.get("node_info"), list) else []
        roles = []
        platform = str(row.get("platform") or "").strip()
        if platform:
            roles.append(platform[:40])
        for node in nodes:
            if not isinstance(node, dict):
                continue
            ha = str(node.get("ha_status") or "").strip()
            hw = str(node.get("hwtype") or node.get("hwmodel") or "").strip()
            if ha and ha not in roles:
                roles.append(ha[:40])
            if hw and hw not in roles:
                roles.append(hw[:40])
        services = _api_services(row.get("service_status"))
        for node in nodes:
            if isinstance(node, dict):
                services.extend(_api_services(node.get("service_status")))
        seen = []
        unique = []
        for service in services:
            if service["name"] in seen:
                continue
            seen.append(service["name"])
            unique.append(service)
        issues = []
        failed = False
        for service in unique:
            state = str(service.get("status") or "")
            if state in _BAD_SERVICE:
                issues.append("%s is %s" % (service["name"], state.lower()))
            if state == "FAILED":
                failed = True
        name = hostname.lower()
        group = "grid" if grid_host and (grid_host == ip or grid_host == name or name.startswith(grid_host + ".")) else "member"
        members.append({
            "hostname": hostname[:128],
            "ip": ip[:64],
            "status": "Failed" if failed else "Working",
            "healthy": not failed,
            "group": group,
            "roles": roles[:8],
            "services": [{"name": service["name"], "running": service.get("status") == "WORKING"} for service in unique[:12]],
            "processes": [],
            "cpu": None,
            "memory": None,
            "diskRoot": None,
            "diskOpt": None,
            "issues": issues[:8],
        })
    members.sort(key=lambda item: (0 if item["group"] == "grid" else 1, item["hostname"]))
    return members[:64]


def _api_services(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    rows = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = str(item.get("service") or "").strip()
        status = str(item.get("status") or "").strip().upper()
        if not name or status in ("", "UNUSED", "INACTIVE"):
            continue
        rows.append({"name": name[:40], "status": status[:20]})
    return rows


def _fill_snmp(member: dict, community: str) -> None:
    if not community or not member.get("ip"):
        return
    try:
        from .snmp import walk
        cpu_rows = walk(member["ip"], 161, community, "1.3.6.1.2.1.25.3.3.1.2", max_reps=10, timeout=2, limit=64)
        if not cpu_rows:
            member["issues"].append("SNMP did not answer")
            member["issues"] = member["issues"][:8]
            return
        descr = walk(member["ip"], 161, community, "1.3.6.1.2.1.25.2.3.1.3", max_reps=15, timeout=2, limit=40)
        size = walk(member["ip"], 161, community, "1.3.6.1.2.1.25.2.3.1.5", max_reps=15, timeout=2, limit=40)
        used = walk(member["ip"], 161, community, "1.3.6.1.2.1.25.2.3.1.6", max_reps=15, timeout=2, limit=40)
        processes = walk(member["ip"], 161, community, "1.3.6.1.2.1.25.4.2.1.2", max_reps=30, timeout=2, limit=1200)
        from .ise import _resources_from_rows
        metrics = _resources_from_rows(cpu_rows, descr, size, used, [])
    except Exception:
        log.warning("infoblox snmp failed for %s", member.get("hostname"))
        member["issues"].append("SNMP did not answer")
        member["issues"] = member["issues"][:8]
        return
    member["cpu"] = metrics["cpu"]
    member["memory"] = metrics["memory"]
    member["diskRoot"] = metrics["diskRoot"]
    member["diskOpt"] = metrics["diskOpt"]
    member["processes"] = _process_services(processes)
    member["issues"].extend(metrics["issues"])
    member["issues"] = member["issues"][:8]


def _process_services(process_rows) -> list[dict]:
    names = []
    for _oid, value in process_rows or []:
        if isinstance(value, (bytes, bytearray)):
            text = value.decode("utf-8", "replace")
        else:
            text = str(value)
        text = text.strip().lower().split()[0] if text.strip() else ""
        if text:
            names.append(text[:64])
    found = []
    for label, markers in _PROCESS_MARKERS:
        if any(name in markers for name in names):
            found.append({"name": label, "running": True})
    return found
