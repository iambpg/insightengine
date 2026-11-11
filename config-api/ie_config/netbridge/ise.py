"""Cisco ISE monitoring node: version, active sessions, and authentication logs.

The Monitoring REST API is XML and HTTP basic auth. Calls go to the
monitoring persona. A policy node that does not run monitoring will not
answer these paths.
"""

from __future__ import annotations

import logging
import re
import socket
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.parse import quote, urlparse

import httpx

log = logging.getLogger("ie-config.netbridge.ise")

MISSING = "ISE URL, username, and password are not configured. Add them in Settings → Vault."
REFUSED = (
    "ISE refused this account on the monitoring API. A login that works in the browser "
    "is not enough. Use an internal admin in the MnT Admin group, and enable the API "
    "under Administration, System, Settings, API Settings."
)
_MAX_BODY = 4_000_000
_LOG_LIMIT = 200
_SESSION = re.compile(
    r"<(?:activeSession|authSession)\b[^>]*>(.*?)</(?:activeSession|authSession)>",
    re.I | re.S,
)


def configured(url: str, username: str, password: str) -> bool:
    return bool((url or "").strip() and (username or "").strip() and (password or "").strip())


def pull(url: str, username: str, password: str, http: httpx.Client | None = None, now: datetime | None = None) -> dict:
    """Read version, the active-session count, and recent authentication sessions."""
    if not configured(url, username, password):
        return _empty(False, MISSING)
    base = url.strip().rstrip("/")
    client = http or httpx.Client(timeout=30.0, verify=False)
    own = http is None
    try:
        version = _get(client, base + "/admin/API/mnt/Version", username, password)
        if not version.get("ok"):
            body = _empty(True, version.get("message") or "ISE did not answer")
            body["ok"] = False
            return body
        count = _get(client, base + "/admin/API/mnt/Session/ActiveCount", username, password)
        start = ((now or datetime.now(timezone.utc)) - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        logs = _get(
            client,
            base + "/admin/API/mnt/Session/AuthList/" + quote(start, safe=":") + "/null",
            username,
            password,
        )
    finally:
        if own:
            client.close()
    rows = _sessions(logs.get("text") or "") if logs.get("ok") else []
    message = ""
    if not logs.get("ok"):
        message = logs.get("message") or "ISE did not return authentication logs."
    elif logs.get("truncated"):
        message = "ISE returned more log data than this page keeps. The newest complete sessions are shown."
    elif not rows:
        message = "ISE answered. No authentication sessions were returned for the last day."
    return {
        "ok": True,
        "configured": True,
        "message": message,
        "version": _tag(version.get("text") or "", "version"),
        "activeSessions": _count(count.get("text") or "") if count.get("ok") else None,
        "rows": rows[:_LOG_LIMIT],
    }


def _empty(ready: bool, message: str) -> dict:
    return {
        "ok": False,
        "configured": ready,
        "message": message,
        "version": "",
        "activeSessions": None,
        "rows": [],
    }


def _get(client: httpx.Client, url: str, username: str, password: str, log_errors: bool = True) -> dict:
    try:
        response = client.get(
            url,
            auth=(username, password),
            headers={"Accept": "application/xml"},
        )
    except httpx.HTTPError:
        log.warning("ise request failed")
        return {"ok": False, "message": "ISE did not answer", "text": ""}
    if response.status_code in (401, 403):
        return {"ok": False, "message": REFUSED, "text": ""}
    if response.status_code >= 400:
        if log_errors:
            log.warning("ise status %s", response.status_code)
        return {"ok": False, "message": "ISE returned HTTP %s" % response.status_code, "text": ""}
    text = response.text or ""
    truncated = len(text) > _MAX_BODY
    if truncated:
        text = text[:_MAX_BODY]
    return {"ok": True, "message": "", "text": text, "truncated": truncated}


def _tag(text: str, name: str) -> str:
    match = re.search(r"<%s\b[^>]*>([^<]*)</%s>" % (re.escape(name), re.escape(name)), text, re.I)
    if not match:
        return ""
    return unescape(match.group(1)).strip()


def _count(text: str) -> int | None:
    found = _tag(text, "count")
    if found.isdigit():
        return int(found)
    match = re.search(r">\s*(\d+)\s*<", text)
    if match:
        return int(match.group(1))
    stripped = text.strip()
    if stripped.isdigit():
        return int(stripped)
    return None


def _sessions(text: str) -> list[dict]:
    rows = []
    for block in _SESSION.findall(text):
        failed = _tag(block, "failed").lower() == "true"
        passed = _tag(block, "passed").lower() == "true"
        if failed:
            result = "Failed"
        elif passed:
            result = "Passed"
        else:
            result = ""
        rows.append({
            "user": _tag(block, "user_name"),
            "mac": _tag(block, "calling_station_id"),
            "nas": _tag(block, "nas_ip_address"),
            "device": _tag(block, "network_device_name"),
            "method": _tag(block, "authentication_method"),
            "server": _tag(block, "acs_server"),
            "result": result,
        })
        if len(rows) >= _LOG_LIMIT:
            break
    return rows


_MAIN_ROLES = (
    "PrimaryAdmin",
    "SecondaryAdmin",
    "PrimaryDedicatedMonitoring",
    "SecondaryDedicatedMonitoring",
    "Standalone",
)
_ROLE_LABEL = {
    "PrimaryAdmin": "Primary Admin",
    "SecondaryAdmin": "Secondary Admin",
    "PrimaryDedicatedMonitoring": "Primary Monitoring",
    "SecondaryDedicatedMonitoring": "Secondary Monitoring",
    "Standalone": "Standalone",
    "Session": "Policy Service",
    "DeviceAdmin": "Device Admin",
}


def node_detail(url: str, username: str, password: str, hostname: str, http: httpx.Client | None = None, community: str = "") -> dict:
    """One deployment node, including the fuller SNMP reading."""
    if not configured(url, username, password):
        return {"ok": False, "configured": False, "message": MISSING, "version": "", "node": None}
    wanted = (hostname or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", wanted):
        return {"ok": False, "configured": True, "message": "That node is not in this deployment.", "version": "", "node": None}
    base = url.strip().rstrip("/")
    client = http or httpx.Client(timeout=30.0, verify=False)
    own = http is None
    try:
        version = _get(client, base + "/admin/API/mnt/Version", username, password)
        if not version.get("ok"):
            return {"ok": False, "configured": True, "message": version.get("message") or "ISE did not answer", "version": "", "node": None}
        nodes = _json_get(client, base + "/api/v1/deployment/node", username, password)
    finally:
        if own:
            client.close()
    if not nodes.get("ok"):
        return {"ok": False, "configured": True, "message": nodes.get("message") or "ISE did not return the deployment.", "version": "", "node": None}
    match = None
    for node in _deployment_nodes(nodes.get("body")):
        if node["hostname"].lower() == wanted.lower():
            match = node
            break
    if match is None:
        return {"ok": False, "configured": True, "message": "That node is not in this deployment.", "version": _tag(version.get("text") or "", "version"), "node": None}
    match["cpus"] = []
    match["uptime"] = ""
    match["description"] = ""
    match["load"] = []
    match["filesystems"] = []
    match["memoryParts"] = []
    _fill_resources(match, community)
    if community and match.get("ip"):
        try:
            extra = _snmp_detail(match["ip"], community)
        except Exception:
            log.warning("ise snmp detail failed for %s", match.get("hostname"))
            extra = None
        if extra:
            match.update(extra)
    return {
        "ok": True,
        "configured": True,
        "message": "",
        "version": _tag(version.get("text") or "", "version"),
        "node": match,
    }


def health(url: str, username: str, password: str, http: httpx.Client | None = None, community: str = "") -> dict:
    """Version, live session load, and the status of every deployment node."""
    if not configured(url, username, password):
        return _health_empty(False, MISSING)
    base = url.strip().rstrip("/")
    client = http or httpx.Client(timeout=30.0, verify=False)
    own = http is None
    try:
        version = _get(client, base + "/admin/API/mnt/Version", username, password)
        if not version.get("ok"):
            body = _health_empty(True, version.get("message") or "ISE did not answer")
            body["ok"] = False
            return body
        count = _get(client, base + "/admin/API/mnt/Session/ActiveCount", username, password)
        nodes = _json_get(client, base + "/api/v1/deployment/node", username, password)
    finally:
        if own:
            client.close()
    parsed = _deployment_nodes(nodes.get("body")) if nodes.get("ok") else []
    for node in parsed:
        _fill_resources(node, community)
    message = ""
    if not nodes.get("ok"):
        message = nodes.get("message") or "ISE did not return the deployment."
    elif not parsed:
        message = "ISE answered, but no nodes were listed."
    return {
        "ok": bool(nodes.get("ok")),
        "configured": True,
        "message": message,
        "version": _tag(version.get("text") or "", "version"),
        "activeSessions": _count(count.get("text") or "") if count.get("ok") else None,
        "nodes": parsed,
    }


_INVENTORY = (
    ("endpoint", "Endpoints"),
    ("identitygroup", "Identity groups"),
    ("networkdevice", "Network devices"),
    ("networkdevicegroup", "Network device groups"),
    ("endpointgroup", "Endpoint groups"),
    ("internaluser", "Internal users"),
    ("adminuser", "Admin users"),
    ("authorizationprofile", "Authorization profiles"),
    ("idstoresequence", "Identity sequences"),
    ("sgt", "Security groups"),
    ("activedirectory", "Active Directory"),
)
_ALARMS_UNAVAILABLE = (
    "ISE did not expose an alarm list on the monitoring API. "
    "Deployment and resource issues on each node are the alarm signal available here."
)
_SESSION_SAMPLE = 12


def operations(
    url: str,
    username: str,
    password: str,
    http: httpx.Client | None = None,
    now: datetime | None = None,
    resolve=None,
    probe=None,
) -> dict:
    """Sessions, ERS inventory counts, and the dependency checks ISE can support."""
    if not configured(url, username, password):
        return _operations_empty(False, MISSING)
    base = url.strip().rstrip("/")
    client = http or httpx.Client(timeout=30.0, verify=False)
    own = http is None
    moment = now or datetime.now(timezone.utc)
    try:
        version = _get(client, base + "/admin/API/mnt/Version", username, password)
        if not version.get("ok"):
            body = _operations_empty(True, version.get("message") or "ISE did not answer")
            body["ok"] = False
            return body
        count = _get(client, base + "/admin/API/mnt/Session/ActiveCount", username, password)
        start = (moment - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        logs = _get(
            client,
            base + "/admin/API/mnt/Session/AuthList/" + quote(start, safe=":") + "/null",
            username,
            password,
        )
        inventory = _inventory(client, base, username, password)
        directories = _directories(client, base, username, password)
        nodes = _json_get(client, base + "/api/v1/deployment/node", username, password)
        certificates = _json_get(client, base + "/api/v1/certs/trusted-certificate", username, password)
        alarms = _get(client, base + "/admin/API/mnt/Alarm", username, password, log_errors=False)
    finally:
        if own:
            client.close()
    recent, rows = _session_sample(logs.get("text") or "") if logs.get("ok") else (None, [])
    session_message = ""
    if not logs.get("ok"):
        session_message = logs.get("message") or "ISE did not return recent authentications."
    elif logs.get("truncated"):
        session_message = "ISE returned more session data than this page keeps. The count covers only the part that was read."
    elif not recent:
        session_message = "No authentications were returned for the last 30 minutes."
    parsed_nodes = _deployment_nodes(nodes.get("body")) if nodes.get("ok") else []
    return {
        "ok": True,
        "configured": True,
        "message": "",
        "version": _tag(version.get("text") or "", "version"),
        "sessions": {
            "active": _count(count.get("text") or "") if count.get("ok") else None,
            "windowMinutes": 30,
            "recent": recent,
            "rows": rows,
            "message": session_message,
        },
        "inventory": inventory,
        "directories": directories["rows"],
        "dependencies": _dependencies(
            parsed_nodes,
            directories,
            certificates if certificates.get("ok") else None,
            moment,
            resolve or _resolve,
            probe or _probe,
        ),
        "alarms": _alarms(alarms),
    }


def _operations_empty(ready: bool, message: str) -> dict:
    return {
        "ok": False,
        "configured": ready,
        "message": message,
        "version": "",
        "sessions": {"active": None, "windowMinutes": 30, "recent": None, "rows": [], "message": message},
        "inventory": [],
        "directories": [],
        "dependencies": [],
        "alarms": {"available": False, "message": message, "rows": []},
    }


def _inventory(client: httpx.Client, base: str, username: str, password: str) -> list[dict]:
    rows = []
    for resource, label in _INVENTORY:
        result = _json_get(client, "%s/ers/config/%s?size=1&page=1" % (base, resource), username, password)
        total = None
        body = result.get("body")
        if isinstance(body, dict) and isinstance(body.get("SearchResult"), dict):
            total = _whole(body["SearchResult"].get("total"))
        rows.append({"name": label, "count": total})
    return rows


def _whole(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _directories(client: httpx.Client, base: str, username: str, password: str) -> dict:
    listed = _json_get(client, base + "/ers/config/activedirectory?size=5&page=1", username, password)
    if not listed.get("ok"):
        return {"ok": False, "rows": []}
    body = listed.get("body") if isinstance(listed.get("body"), dict) else {}
    search = body.get("SearchResult") if isinstance(body.get("SearchResult"), dict) else {}
    resources = search.get("resources") if isinstance(search.get("resources"), list) else []
    rows = []
    for resource in resources[:5]:
        if not isinstance(resource, dict):
            continue
        name = _clean(str(resource.get("name") or ""), 80)
        domain = ""
        href = resource.get("link").get("href") if isinstance(resource.get("link"), dict) else ""
        path = urlparse(href).path if isinstance(href, str) else ""
        if re.fullmatch(r"/ers/config/activedirectory/[A-Za-z0-9-]{1,80}", path or ""):
            detail = _json_get(client, base + path, username, password)
            obj = _directory_object(detail.get("body"))
            if obj:
                name = _clean(str(obj.get("name") or name), 80)
                domain = _clean(str(obj.get("domain") or ""), 120)
        if name or domain:
            rows.append({"name": name, "domain": domain})
    return {"ok": True, "rows": rows}


def _directory_object(body) -> dict | None:
    if not isinstance(body, dict):
        return None
    for key in ("ERSActiveDirectory", "ActiveDirectory"):
        if isinstance(body.get(key), dict):
            return body[key]
    if "domain" in body or "name" in body:
        return body
    return None


def _session_sample(text: str) -> tuple[int | None, list[dict]]:
    blocks = _SESSION.findall(text or "")
    rows = []
    for block in blocks[:_SESSION_SAMPLE]:
        rows.append({
            "user": _clean(_tag(block, "user_name"), 128),
            "mac": _clean(_tag(block, "calling_station_id"), 64),
            "client": _clean(_tag(block, "framed_ip_address") or _tag(block, "framed_ipv6_address"), 64),
            "nas": _clean(_tag(block, "nas_ip_address"), 64),
            "server": _clean(_tag(block, "acs_server") or _tag(block, "server"), 128),
        })
    return len(blocks), rows


def _clean(value: str, limit: int) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", "", value or "").strip()[:limit]


def _dependencies(nodes: list[dict], directories: dict, certificates, moment: datetime, resolve, probe) -> list[dict]:
    return [
        _dns_dependency(nodes, resolve),
        _directory_dependency(directories),
        _reach_dependency(nodes, probe),
        _certificate_dependency(certificates, moment),
    ]


def _dns_dependency(nodes: list[dict], resolve) -> dict:
    checked = failed = mismatched = matched = 0
    items = []
    for node in nodes:
        hostname = _clean(str(node.get("hostname") or "Node"), 128)
        fqdn = str(node.get("fqdn") or "").strip()
        ip = str(node.get("ip") or "").strip()
        if not fqdn or not ip:
            items.append({"name": hostname, "status": "unknown", "detail": "No DNS name was listed."})
            continue
        checked += 1
        try:
            found = resolve(fqdn)
        except Exception:
            failed += 1
            items.append({"name": hostname, "status": "unknown", "detail": "The name did not resolve."})
            continue
        addresses = {str(item).strip() for item in (found or set()) if str(item).strip()}
        if not addresses:
            failed += 1
            items.append({"name": hostname, "status": "unknown", "detail": "The name did not resolve."})
        elif ip in addresses:
            matched += 1
            items.append({"name": hostname, "status": "ok", "detail": "Resolves to the deployment address."})
        else:
            mismatched += 1
            items.append({"name": hostname, "status": "warning", "detail": "Resolves to a different address."})
    if checked == 0:
        summary = {"name": "DNS", "status": "unknown", "detail": "Node DNS names were not listed."}
    elif failed == checked:
        summary = {
            "name": "DNS",
            "status": "unknown",
            "detail": "InsightEngine cannot resolve the %d node names. ISE does not expose its DNS servers here, so this is not an ISE resolver failure." % checked,
        }
    elif failed or mismatched:
        summary = {
            "name": "DNS",
            "status": "warning",
            "detail": "%d of %d node names resolve to the deployment address." % (matched, checked),
        }
    else:
        summary = {"name": "DNS", "status": "ok", "detail": "All %d node names resolve to their deployment addresses." % checked}
    summary["rows"] = items[:64]
    return summary


def _directory_dependency(directories: dict) -> dict:
    if not directories.get("ok"):
        return {"name": "Active Directory", "status": "unknown", "detail": "ISE did not return Active Directory."}
    rows = directories.get("rows") or []
    if not rows:
        return {"name": "Active Directory", "status": "warning", "detail": "No Active Directory is configured."}
    parts = []
    for row in rows[:3]:
        if row.get("name") and row.get("domain"):
            parts.append("%s for %s" % (row["name"], row["domain"]))
        else:
            parts.append(row.get("name") or row.get("domain") or "")
    return {"name": "Active Directory", "status": "ok", "detail": "Configured: %s." % ", ".join(part for part in parts if part)}


def _reach_dependency(nodes: list[dict], probe) -> dict:
    checked = open_count = 0
    items = []
    for node in nodes:
        hostname = _clean(str(node.get("hostname") or "Node"), 128)
        ip = str(node.get("ip") or "").strip()
        if not ip:
            items.append({"name": hostname, "status": "unknown", "detail": "No address was listed."})
            continue
        checked += 1
        try:
            opened = bool(probe(ip))
        except Exception:
            opened = False
        if opened:
            open_count += 1
            items.append({"name": hostname, "status": "ok", "detail": "Port 443 accepted a connection."})
        else:
            items.append({"name": hostname, "status": "warning", "detail": "Port 443 did not answer."})
    if checked == 0:
        summary = {"name": "Reachability", "status": "unknown", "detail": "No node addresses were listed."}
    elif open_count == checked:
        summary = {"name": "Reachability", "status": "ok", "detail": "All %d nodes accepted a connection on port 443." % checked}
    else:
        summary = {
            "name": "Reachability",
            "status": "warning",
            "detail": "%d of %d nodes accepted a connection on port 443." % (open_count, checked),
        }
    summary["rows"] = items[:64]
    return summary


def _certificate_dependency(payload, moment: datetime) -> dict:
    rows = []
    if isinstance(payload, dict):
        body = payload.get("body")
        if isinstance(body, dict) and isinstance(body.get("response"), list):
            rows = [row for row in body["response"] if isinstance(row, dict)]
    if payload is None:
        return {"name": "Certificates", "status": "unknown", "detail": "ISE did not return trusted certificates."}
    expired = soon = readable = 0
    nearest = None
    attention = []
    for row in rows:
        parsed = _parse_time(str(row.get("expirationDate") or ""))
        if parsed is None:
            continue
        readable += 1
        days = int((parsed - moment).total_seconds() // 86400)
        item = {"name": _clean(str(row.get("friendlyName") or "Certificate"), 80), "days": days, "date": parsed.date().isoformat()}
        if nearest is None or days < nearest["days"]:
            nearest = item
        if days < 0:
            expired += 1
            attention.append(item)
        elif days < 30:
            soon += 1
            attention.append(item)
    attention.sort(key=lambda item: item["days"])
    if not rows:
        return {"name": "Certificates", "status": "unknown", "detail": "ISE returned no trusted certificates."}
    if readable == 0:
        return {"name": "Certificates", "status": "unknown", "detail": "ISE returned %d trusted certificates, but the expiry dates were not readable." % len(rows)}
    if expired:
        status = "warning"
        detail = "%d of %d trusted certificates are expired." % (expired, len(rows))
    elif soon:
        status = "warning"
        detail = "%d of %d trusted certificates expire within 30 days." % (soon, len(rows))
    else:
        status = "ok"
        detail = "%d trusted certificates. None expire within 30 days." % len(rows)
    if nearest:
        when = "expired %d days ago" % abs(nearest["days"]) if nearest["days"] < 0 else "expires in %d days" % nearest["days"]
        detail = "%s Nearest is %s, which %s." % (detail, nearest["name"], when)
    return {"name": "Certificates", "status": status, "detail": detail, "attention": attention[:8]}


def _parse_time(value: str):
    text = (value or "").strip()
    if not text:
        return None
    named = re.fullmatch(r"([A-Za-z]{3}) ([A-Za-z]{3}) +(\d{1,2}) (\d{2}:\d{2}:\d{2}) [A-Za-z]+ (\d{4})", text)
    if named:
        try:
            stamp = "%s %s %s %s %s" % (named.group(1), named.group(2), named.group(3), named.group(4), named.group(5))
            return datetime.strptime(stamp, "%a %b %d %H:%M:%S %Y").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _resolve(host: str) -> set[str]:
    found = set()
    for item in socket.getaddrinfo(host, None):
        address = item[4][0] if item and item[4] else ""
        if address:
            found.add(address)
    return found


def _probe(ip: str) -> bool:
    if not re.fullmatch(r"[0-9A-Fa-f:.]+", ip or ""):
        return False
    sock = socket.socket()
    try:
        sock.settimeout(2)
        return sock.connect_ex((ip, 443)) == 0
    except OSError:
        return False
    finally:
        sock.close()


def _alarms(result: dict) -> dict:
    if not result.get("ok"):
        return {"available": False, "message": _ALARMS_UNAVAILABLE, "rows": []}
    rows = []
    for block in re.findall(r"<alarm\b[^>]*>(.*?)</alarm>", result.get("text") or "", re.I | re.S):
        name = _clean(_tag(block, "name") or _tag(block, "alarmName") or _tag(block, "message"), 160)
        if not name:
            continue
        rows.append({"name": name, "severity": _clean(_tag(block, "severity"), 40)})
        if len(rows) >= 20:
            break
    return {"available": True, "message": "", "rows": rows}


def _health_empty(ready: bool, message: str) -> dict:
    return {
        "ok": False,
        "configured": ready,
        "message": message,
        "version": "",
        "activeSessions": None,
        "nodes": [],
    }


def _json_get(client: httpx.Client, url: str, username: str, password: str) -> dict:
    try:
        response = client.get(url, auth=(username, password), headers={"Accept": "application/json"})
    except httpx.HTTPError:
        log.warning("ise request failed")
        return {"ok": False, "message": "ISE did not answer", "body": None}
    if response.status_code in (401, 403):
        return {"ok": False, "message": REFUSED, "body": None}
    if response.status_code >= 400:
        log.warning("ise status %s", response.status_code)
        return {"ok": False, "message": "ISE returned HTTP %s" % response.status_code, "body": None}
    try:
        body = response.json()
    except ValueError:
        return {"ok": False, "message": "ISE did not return the deployment.", "body": None}
    return {"ok": True, "message": "", "body": body}


def _role_label(token: str) -> str:
    if token in _ROLE_LABEL:
        return _ROLE_LABEL[token]
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", token).replace("_", " ").strip() or token


def _tokens(value) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if not isinstance(value, list):
        return []
    tokens = []
    for item in value:
        if isinstance(item, str) and item.strip():
            tokens.append(item.strip())
        elif isinstance(item, dict):
            name = str(item.get("name") or item.get("serviceType") or "").strip()
            if name:
                tokens.append(name)
    return tokens


def _deployment_nodes(body) -> list[dict]:
    rows = body
    if isinstance(body, dict):
        rows = body.get("response")
        if isinstance(rows, dict):
            rows = [rows]
    if not isinstance(rows, list):
        return []
    nodes = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        hostname = str(row.get("hostname") or row.get("name") or "").strip()
        if not hostname:
            continue
        raw = _tokens(row.get("roles")) + _tokens(row.get("services"))
        seen = []
        for token in raw:
            if token not in seen:
                seen.append(token)
        main = any(token in _MAIN_ROLES for token in seen)
        status = str(row.get("nodeStatus") or "Unknown").strip() or "Unknown"
        rank = min((_MAIN_ROLES.index(token) for token in seen if token in _MAIN_ROLES), default=99)
        nodes.append({
            "hostname": hostname[:128],
            "fqdn": str(row.get("fqdn") or "")[:255],
            "ip": str(row.get("ipAddress") or row.get("ip") or "")[:64],
            "status": status[:64],
            "healthy": status.lower() == "connected",
            "group": "main" if main else "policy",
            "roles": [_role_label(token) for token in seen][:8],
            "cpu": None,
            "memory": None,
            "diskRoot": None,
            "diskOpt": None,
            "services": [],
            "issues": [],
            "ntp": None,
            "directory": None,
            "_rank": rank,
        })
    nodes.sort(key=lambda item: (0 if item["group"] == "main" else 1, item["_rank"], item["hostname"]))
    for item in nodes:
        item.pop("_rank", None)
    return nodes[:64]


_SERVICE_MARKERS = (
    ("Application Server", "java"),
    ("Web", "nginx"),
    ("Database", "oracle"),
    ("Cache", "redis-server"),
    ("Messaging", "rabbitmq"),
    ("API database", "postgres"),
    ("Containers", "docker"),
    ("Metrics", "ise-prometheus"),
)


def _fill_resources(node: dict, community: str) -> None:
    if not node.get("healthy"):
        node["issues"].append("Deployment status is %s" % (node.get("status") or "Unknown"))
    if not community or not node.get("ip"):
        return
    try:
        metrics = _snmp_resources(node["ip"], community)
    except Exception:
        log.warning("ise snmp failed for %s", node.get("hostname") or node.get("ip"))
        node["issues"].append("SNMP did not answer")
        return
    if not metrics:
        node["issues"].append("SNMP did not answer")
        return
    node["cpu"] = metrics["cpu"]
    node["memory"] = metrics["memory"]
    node["diskRoot"] = metrics["diskRoot"]
    node["diskOpt"] = metrics["diskOpt"]
    node["services"] = metrics["services"]
    node["ntp"] = metrics["ntp"]
    node["directory"] = metrics["directory"]
    node["issues"].extend(metrics["issues"])
    node["issues"] = node["issues"][:8]


def _percent(used, size) -> int | None:
    try:
        used_n = int(used)
        size_n = int(size)
    except (TypeError, ValueError):
        return None
    if size_n <= 0:
        return None
    return max(0, min(100, int(round(100.0 * used_n / size_n))))


def _snmp_resources(host: str, community: str) -> dict | None:
    from .snmp import walk
    cpu_rows = walk(host, 161, community, "1.3.6.1.2.1.25.3.3.1.2", max_reps=10, timeout=2, limit=64)
    if not cpu_rows:
        return None
    descr = walk(host, 161, community, "1.3.6.1.2.1.25.2.3.1.3", max_reps=15, timeout=2, limit=40)
    size = walk(host, 161, community, "1.3.6.1.2.1.25.2.3.1.5", max_reps=15, timeout=2, limit=40)
    used = walk(host, 161, community, "1.3.6.1.2.1.25.2.3.1.6", max_reps=15, timeout=2, limit=40)
    processes = walk(host, 161, community, "1.3.6.1.2.1.25.4.2.1.2", max_reps=30, timeout=2, limit=1200)
    return _resources_from_rows(cpu_rows, descr, size, used, processes)


def _index(oid: str) -> str:
    return str(oid).rsplit(".", 1)[-1]


def _text(value) -> str:
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace")
    return str(value)


def _resources_from_rows(cpu_rows, descr_rows, size_rows, used_rows, process_rows) -> dict:
    loads = []
    for _oid, value in cpu_rows or []:
        try:
            loads.append(int(value))
        except (TypeError, ValueError):
            continue
    cpu = int(round(sum(loads) / len(loads))) if loads else None
    sizes = {_index(oid): value for oid, value in size_rows or []}
    used = {_index(oid): value for oid, value in used_rows or []}
    named = {}
    for oid, value in descr_rows or []:
        named[_text(value).strip()] = _percent(used.get(_index(oid)), sizes.get(_index(oid)))
    memory = named.get("Physical memory")
    disk_root = named.get("/")
    disk_opt = named.get("/opt")
    blob = " ".join(_text(value).lower() for _oid, value in process_rows or [])
    names = []
    for _oid, value in process_rows or []:
        text = _text(value).strip().lower().split()[0] if _text(value).strip() else ""
        if text:
            names.append(text[:64])
    services = []
    for label, marker in _SERVICE_MARKERS:
        if marker in blob:
            services.append({"name": label, "running": True})
    ntp = any(name in ("chronyd", "ntpd") for name in names)
    directory = any(name == "sssd" or name.startswith("sssd_") or name == "winbindd" for name in names)
    if ntp:
        services.append({"name": "NTP", "running": True})
    if directory:
        services.append({"name": "Directory", "running": True})
    issues = []
    if cpu is not None and cpu >= 90:
        issues.append("CPU is %s%%" % cpu)
    if memory is not None and memory >= 90:
        issues.append("Memory is %s%%" % memory)
    if disk_root is not None and disk_root >= 90:
        issues.append("Root disk is %s%% full" % disk_root)
    if disk_opt is not None and disk_opt >= 90:
        issues.append("Application disk is %s%% full" % disk_opt)
    return {
        "cpu": cpu,
        "memory": memory,
        "diskRoot": disk_root,
        "diskOpt": disk_opt,
        "services": services,
        "issues": issues,
        "ntp": ntp,
        "directory": directory,
    }


def _snmp_detail(host: str, community: str) -> dict | None:
    from .snmp import walk
    cpu_rows = walk(host, 161, community, "1.3.6.1.2.1.25.3.3.1.2", max_reps=10, timeout=2, limit=64)
    if not cpu_rows:
        return None
    descr = walk(host, 161, community, "1.3.6.1.2.1.25.2.3.1.3", max_reps=15, timeout=2, limit=40)
    size = walk(host, 161, community, "1.3.6.1.2.1.25.2.3.1.5", max_reps=15, timeout=2, limit=40)
    used = walk(host, 161, community, "1.3.6.1.2.1.25.2.3.1.6", max_reps=15, timeout=2, limit=40)
    units = walk(host, 161, community, "1.3.6.1.2.1.25.2.3.1.4", max_reps=15, timeout=2, limit=40)
    uptime = walk(host, 161, community, "1.3.6.1.2.1.1.3", max_reps=1, timeout=2, limit=1)
    descr_sys = walk(host, 161, community, "1.3.6.1.2.1.1.1", max_reps=1, timeout=2, limit=1)
    load = walk(host, 161, community, "1.3.6.1.4.1.2021.10.1.3", max_reps=3, timeout=2, limit=3)
    cpus = []
    for _oid, value in cpu_rows:
        try:
            cpus.append(int(value))
        except (TypeError, ValueError):
            continue
    ticks = uptime[0][1] if uptime else None
    description = _text(descr_sys[0][1]).replace("\x00", "").strip()[:300] if descr_sys else ""
    loads = []
    for _oid, value in load:
        text = _text(value).strip()
        if text:
            loads.append(text[:16])
    return {
        "cpus": cpus[:64],
        "uptime": _uptime(ticks),
        "description": description,
        "load": loads[:3],
        "filesystems": _storage_entries(descr, size, used, units, files=True),
        "memoryParts": _storage_entries(descr, size, used, units, files=False),
    }


def _uptime(ticks) -> str:
    try:
        seconds = int(ticks) // 100
    except (TypeError, ValueError):
        return ""
    if seconds < 0:
        return ""
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return "%d days %d hours" % (days, hours)
    if hours:
        return "%d hours %d minutes" % (hours, minutes)
    return "%d minutes" % minutes


def _size_label(amount) -> str:
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return ""
    if value < 0:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            rounded = round(value, 1)
            shown = str(int(rounded)) if abs(rounded - int(rounded)) < 0.05 else ("%.1f" % rounded)
            return "%s %s" % (shown, unit)
        value /= 1024.0
    return ""


_MEMORY_NAMES = ("Physical memory", "Virtual memory", "Swap space", "Memory buffers", "Cached memory", "Shared memory")
_SKIP_DISK = ("/dev", "/sys", "/run", "/proc")


def _storage_entries(descr_rows, size_rows, used_rows, unit_rows, files: bool) -> list[dict]:
    sizes = {_index(oid): value for oid, value in size_rows or []}
    used = {_index(oid): value for oid, value in used_rows or []}
    units = {_index(oid): value for oid, value in unit_rows or []}
    rows = []
    for oid, value in descr_rows or []:
        name = _text(value).strip()
        if not name:
            continue
        is_file = name.startswith("/")
        if files and (not is_file or name.startswith(_SKIP_DISK) or "overlay-containers" in name):
            continue
        if not files and name not in _MEMORY_NAMES:
            continue
        idx = _index(oid)
        percent = _percent(used.get(idx), sizes.get(idx))
        try:
            block = int(units.get(idx) or 1)
            used_b = int(used.get(idx) or 0) * block
            size_b = int(sizes.get(idx) or 0) * block
        except (TypeError, ValueError):
            used_b = 0
            size_b = 0
        rows.append({
            "name": name[:80],
            "percent": percent,
            "used": _size_label(used_b),
            "size": _size_label(size_b),
        })
    rows.sort(key=lambda item: (-(item["percent"] or 0), item["name"]))
    return rows[:24]
