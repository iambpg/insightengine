"""Write SNMP exporter auths, the http_sd auth map, and Netdisco device_auth.

Secrets are written only to mode-0600 files. Log lines carry counts and auth
names (hashes), never communities or passphrases.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

import yaml

from .snmp_profiles import (
    SCOPE_KEYS,
    SnmpProfileError,
    SECRET_KEYS,
    auth_name,
    build_context_data,
    escape_exporter,
    exporter_auth,
    monitoring_snmp_from_context,
    netdisco_entry,
    public_view,
    resolve_device,
    splice_auths,
    validate_profile,
)

log = logging.getLogger("ie.snmp")

AUTH_MAP_NAME = "auth-by-ip.yml"
RUNTIME_NAME = "snmp.runtime.yml"
ASSIGNMENTS_NAME = "assignments.json"
PROFILES_NAME = "profiles.json"
MODE_NAME = "mode.json"


def snmp_dir(settings) -> str:
    path = getattr(settings, "snmp_dir", "") or ""
    if path:
        return path
    return os.path.join(getattr(settings, "config_root", "") or ".", "data", "snmp")


def _atomic_bytes(path: str, data: bytes, mode: int) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def read_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write_mode(directory: str, mode: str) -> None:
    if mode not in ("context", "file"):
        raise SnmpProfileError("secret mode must be context or file")
    _atomic_bytes(os.path.join(directory, MODE_NAME), json.dumps({"secret_mode": mode}).encode(), 0o600)


def read_mode(directory: str) -> str:
    data = read_json(os.path.join(directory, MODE_NAME), {})
    mode = data.get("secret_mode") if isinstance(data, dict) else None
    return mode if mode in ("context", "file") else "context"


def read_file_profiles(directory: str) -> dict:
    data = read_json(os.path.join(directory, PROFILES_NAME), {})
    profiles = data.get("profiles") if isinstance(data, dict) else None
    return profiles if isinstance(profiles, dict) else {}


def write_file_profiles(directory: str, profiles: dict) -> None:
    _atomic_bytes(
        os.path.join(directory, PROFILES_NAME),
        json.dumps({"profiles": profiles}, indent=2).encode(),
        0o600,
    )


def load_auth_map(path: str) -> dict[str, str]:
    """IP to auth name. No secrets. Missing file means the .env fallback."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for ip, name in data.items():
        if isinstance(ip, str) and isinstance(name, str) and name:
            out[ip] = name
    return out


def device_ip(device: dict) -> str:
    raw = device.get("primary_ip") or device.get("primary_ip4") or ""
    if isinstance(raw, dict):
        raw = raw.get("address") or ""
    return str(raw).split("/")[0].strip()


def device_role(device: dict) -> str:
    role = device.get("role")
    if isinstance(role, dict):
        return str(role.get("slug") or role.get("name") or "")
    return str(role or "")


def iter_resolved(devices: list[dict], env: dict, file_profiles: dict) -> list[dict]:
    """One row per device that has an address. ``source=env`` is the fallback."""
    rows = []
    for device in devices:
        ip = device_ip(device)
        if not ip:
            continue
        resolved = resolve_device(device.get("config_context"), env, file_profiles)
        rows.append({
            "id": device.get("id"),
            "name": device.get("name") or "",
            "ip": ip,
            "role": device_role(device),
            "resolved": resolved,
        })
    return rows


def auth_map_from_rows(rows: list[dict]) -> dict[str, str]:
    """Only context and file sources override the job default. Env fallback does not."""
    mapping = {}
    for row in rows:
        resolved = row["resolved"]
        if resolved.get("source") in ("context", "file") and resolved.get("auth"):
            mapping[row["ip"]] = resolved["auth"]
    return mapping


def grouped_profiles(rows: list[dict]) -> list[dict]:
    """Distinct non-env profiles, each with the IPs that use it."""
    groups: dict[str, dict] = {}
    for row in rows:
        resolved = row["resolved"]
        if resolved.get("source") not in ("context", "file"):
            continue
        profile = resolved.get("profile")
        if not profile:
            continue
        key = resolved["auth"]
        bucket = groups.get(key)
        if bucket is None:
            groups[key] = {"auth": key, "profile": profile, "ips": [row["ip"]], "source": resolved["source"]}
        elif row["ip"] not in bucket["ips"]:
            bucket["ips"].append(row["ip"])
    return list(groups.values())


def write_outputs(directory: str, base_snmp_yml: str, rows: list[dict]) -> dict:
    """Write the auth map (no secrets) and the runtime exporter file (secrets, mode 0600)."""
    os.makedirs(directory, exist_ok=True)
    mapping = auth_map_from_rows(rows)
    map_path = os.path.join(directory, AUTH_MAP_NAME)
    _atomic_bytes(map_path, yaml.safe_dump(mapping, sort_keys=True).encode(), 0o644)
    groups = grouped_profiles(rows)
    extra = {}
    for group in groups:
        body = exporter_auth(group["profile"])
        # snmp_exporter does not expand env vars in ``community``, so it must not be escaped.
        extra[group["auth"]] = {key: escape_exporter(value) if isinstance(value, str) and key != "community" else value for key, value in body.items()}
    # Only the generated auths. The exporter layers this file over the committed
    # snmp.yml (see config/snmp/snmp-exporter-run.sh). snmp_exporter rejects a key that
    # appears in two config files, so the base auths and modules must not be repeated here.
    runtime = "# Generated by ie-config. Do not edit.\n" + yaml.safe_dump({"auths": extra}, sort_keys=False)
    runtime_path = os.path.join(directory, RUNTIME_NAME)
    _atomic_bytes(runtime_path, runtime.encode(), 0o600)
    assignments = []
    for group in groups:
        item = {"auth": group["auth"], "ips": group["ips"], "source": group["source"]}
        item.update(group["profile"])
        assignments.append(item)
    _atomic_bytes(
        os.path.join(directory, ASSIGNMENTS_NAME),
        json.dumps({"groups": assignments}).encode(),
        0o600,
    )
    return {"devices": len(rows), "profiles": len(groups), "mapped": len(mapping)}


def netdisco_yaml_entries(groups: list[dict]) -> str:
    import io
    items = []
    for group in groups:
        items.append(netdisco_entry(group["profile"], group["ips"], group["auth"]))
    if not items:
        return ""
    buf = io.StringIO()
    yaml.safe_dump(items, buf, sort_keys=False)
    return buf.getvalue()


def splice_device_auth(rendered: str, extra_yaml_list: str) -> str:
    """Put specific ``only:`` entries before the template default."""
    if not extra_yaml_list.strip():
        return rendered
    needle = "device_auth:"
    idx = rendered.find(needle)
    if idx == -1:
        return rendered.rstrip() + "\ndevice_auth:\n" + _indent_yaml_list(extra_yaml_list)
    insert_at = idx + len(needle)
    # extra_yaml_list is a YAML list starting with "- ".
    indented = _indent_yaml_list(extra_yaml_list)
    return rendered[:insert_at] + "\n" + indented + rendered[insert_at:]


def _indent_yaml_list(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if not line.strip():
            continue
        lines.append("  " + line)
    return "\n".join(lines) + ("\n" if lines else "")


def reload_exporters(urls: list[str], opener: Callable | None = None) -> list[str]:
    """POST /-/reload. Returns the URLs that accepted it. Errors omit response bodies."""
    opener = opener or urllib.request.urlopen
    ok = []
    for url in urls:
        target = url.rstrip("/") + "/-/reload"
        request = urllib.request.Request(target, data=b"", method="POST")
        try:
            with opener(request, timeout=5) as resp:
                if getattr(resp, "status", 200) < 300:
                    ok.append(url)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            log.warning("snmp exporter reload failed for %s: %s", url, exc.__class__.__name__)
    return ok


def default_exporter_urls() -> list[str]:
    raw = os.environ.get("SNMP_EXPORTER_RELOAD_URLS", "")
    if raw.strip():
        return [part.strip() for part in raw.split(",") if part.strip()]
    return [
        "http://snmp-exporter-1:9116",
        "http://snmp-exporter-2:9116",
        "http://snmp-exporter-3:9116",
        "http://snmp-exporter-4:9116",
    ]


def exporter_probe(host: str, auth: str, port: int = 161, urls: list[str] | None = None, opener: Callable | None = None) -> int:
    """One scrape of the ``system`` module through an exporter. Returns the HTTP status.

    SNMPv3 cannot be tested from ie-config directly (it has no v3 stack), so the
    exporter, which already holds the generated auth, does the request. Raises OSError
    when no exporter answers. The response body is never read.
    """
    opener = opener or urllib.request.urlopen
    target = host if int(port) == 161 else "%s:%s" % (host, int(port))
    query = urllib.parse.urlencode({"target": target, "auth": auth, "module": "system"})
    last: Exception = OSError("no exporter")
    for base in urls or default_exporter_urls():
        try:
            with opener(base.rstrip("/") + "/snmp?" + query, timeout=15) as resp:
                return int(getattr(resp, "status", 200))
        except urllib.error.HTTPError as exc:
            return int(exc.code)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
    raise OSError(str(last.__class__.__name__))


def fetch_devices(get_json: Callable[[str], Any]) -> list[dict]:
    """Walk active devices and attach each rendered config_context.

    ``get_json`` performs a GET and returns parsed JSON. It must not log bodies.
    """
    devices: list[dict] = []
    url = "/api/dcim/devices/?status=active&limit=100"
    while url:
        page = get_json(url)
        if not isinstance(page, dict):
            break
        for summary in page.get("results") or []:
            if not isinstance(summary, dict) or not summary.get("id"):
                continue
            detail = get_json(
                "/api/dcim/devices/%s/?exclude=interfaces,front_ports,rear_ports,console_ports,power_ports,power_outlets"
                % summary["id"]
            )
            if isinstance(detail, dict):
                devices.append(detail)
        url = page.get("next") or ""
        if url.startswith("http://") or url.startswith("https://"):
            # Caller passes site-relative paths. Drop the origin if NetBox returned one.
            marker = "/api/"
            pos = url.find(marker)
            url = url[pos:] if pos != -1 else ""
    return devices


def context_public_rows(contexts: list[dict], file_profiles: dict, assignments: Any = None) -> list[dict]:
    """Settings list. Secrets from either storage are reduced to presence flags.

    ``assignments`` is the content of assignments.json from the last sync; it supplies
    ``applies_to`` (device addresses per auth name). Without it the list is empty.
    """
    ips_by_auth: dict[str, list[str]] = {}
    groups = assignments.get("groups") if isinstance(assignments, dict) else None
    for group in groups if isinstance(groups, list) else []:
        if isinstance(group, dict) and isinstance(group.get("auth"), str) and isinstance(group.get("ips"), list):
            ips_by_auth[group["auth"]] = [str(ip) for ip in group["ips"]]
    rows = []
    for ctx in contexts:
        if not isinstance(ctx, dict):
            continue
        data = ctx.get("data") if isinstance(ctx.get("data"), dict) else {}
        raw = monitoring_snmp_from_context(data)
        if raw is None:
            continue
        scopes = {key: _scope_names(ctx.get(key)) for key in SCOPE_KEYS}
        name = str(ctx.get("name") or "")
        weight = ctx.get("weight")
        try:
            weight_i = int(weight) if weight is not None else None
        except (TypeError, ValueError):
            weight_i = None
        profile = None
        source = "context"
        profile_name = ""
        if isinstance(raw, dict) and raw.get("profile") and "version" not in raw:
            profile_name = str(raw.get("profile"))
            stored = file_profiles.get(profile_name)
            source = "file"
            if isinstance(stored, dict):
                try:
                    profile = validate_profile(stored)
                except SnmpProfileError:
                    profile = None
        elif isinstance(raw, dict) and raw.get("version"):
            try:
                profile = validate_profile(raw)
            except SnmpProfileError:
                profile = None
        if profile is None:
            rows.append({
                "name": name,
                "id": ctx.get("id"),
                "weight": weight_i,
                "scopes": scopes,
                "source": source,
                "profile_name": profile_name,
                "auth": "",
                "invalid": True,
            })
            continue
        view = public_view(profile, auth=auth_name(profile), source=source, scopes=scopes, weight=weight_i, name=name or profile_name, ips=ips_by_auth.get(auth_name(profile)))
        view["id"] = ctx.get("id")
        view["profile_name"] = profile_name
        view["invalid"] = False
        rows.append(view)
    return rows


def _scope_names(value: Any) -> list:
    if not isinstance(value, list):
        return []
    names = []
    for item in value:
        if isinstance(item, dict):
            names.append(item.get("slug") or item.get("name") or item.get("id"))
        else:
            names.append(item)
    return names


def encode_oid(oid: str) -> bytes:
    parts = [int(part) for part in oid.split(".") if part != ""]
    if len(parts) < 2:
        raise SnmpProfileError("oid")
    body = bytes([(40 * parts[0] + parts[1]) & 0xFF])
    for part in parts[2:]:
        body += _base128(part)
    return bytes([0x06, len(body)]) + body


def _base128(value: int) -> bytes:
    chunks = [value & 0x7F]
    value >>= 7
    while value:
        chunks.append(0x80 | (value & 0x7F))
        value >>= 7
    return bytes(reversed(chunks))


def _tlv(tag: int, body: bytes) -> bytes:
    if len(body) < 128:
        length = bytes([len(body)])
    else:
        size = len(body).to_bytes((len(body).bit_length() + 7) // 8, "big")
        length = bytes([0x80 | len(size)]) + size
    return bytes([tag]) + length + body


def snmp_v2c_get_packet(community: str, oid: str = "1.3.6.1.2.1.1.1.0", request_id: int = 1) -> bytes:
    varbind = _tlv(0x30, encode_oid(oid) + bytes([0x05, 0x00]))
    varbinds = _tlv(0x30, varbind)
    pdu_body = _tlv(0x02, request_id.to_bytes(2, "big")) + _tlv(0x02, b"\x00") + _tlv(0x02, b"\x00") + varbinds
    pdu = _tlv(0xA0, pdu_body)
    message = _tlv(0x02, b"\x01") + _tlv(0x04, community.encode("utf-8")) + pdu
    return _tlv(0x30, message)


def snmp_v2c_get(host: str, community: str, port: int = 161, oid: str = "1.3.6.1.2.1.1.1.0", timeout: float = 2.0, send: Callable | None = None) -> dict:
    """One SNMPv2c GET. The result never includes the community."""
    packet = snmp_v2c_get_packet(community, oid)
    if send is None:
        def send(payload, host, port, timeout):
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.settimeout(timeout)
                sock.sendto(payload, (host, int(port)))
                data, _addr = sock.recvfrom(4096)
                return data
            finally:
                sock.close()
    try:
        data = send(packet, host, int(port), timeout)
    except (TimeoutError, socket.timeout, OSError):
        return {"ok": False, "error": "timeout", "version": "2c"}
    if not data:
        return {"ok": False, "error": "empty", "version": "2c"}
    # A response is a SEQUENCE. Do not echo it; it can repeat the community.
    if data[0] != 0x30:
        return {"ok": False, "error": "bad_response", "version": "2c"}
    return {"ok": True, "version": "2c", "oid": oid}


def _netbox_json(settings, method: str, path: str, payload: dict | None = None) -> Any:
    """NetBox call. Failures raise SnmpProfileError with a status code and no body."""
    import httpx
    from .fleet import netbox_headers
    headers = netbox_headers(settings.netbox_token_file)
    if not headers.get("Authorization"):
        raise SnmpProfileError("netbox token is not configured")
    url = path if path.startswith("http://") or path.startswith("https://") else settings.netbox_url + path
    with httpx.Client(timeout=30.0) as client:
        response = client.request(method, url, headers=headers, json=payload)
    if response.status_code >= 300:
        raise SnmpProfileError("netbox http %s" % response.status_code)
    if not response.content:
        return {}
    return response.json()


def list_contexts(settings) -> list[dict]:
    page = _netbox_json(settings, "GET", "/api/extras/config-contexts/?limit=200")
    results = page.get("results") if isinstance(page, dict) else None
    return results if isinstance(results, list) else []


def save_context_profile(settings, body: dict) -> dict:
    """Create or update one config context. Empty secret fields keep the stored value."""
    if body.get("devices") or (isinstance(body.get("scopes"), dict) and body["scopes"].get("devices")):
        raise SnmpProfileError("SNMP profiles are not scoped to a single device")
    directory = snmp_dir(settings)
    mode = read_mode(directory)
    name = str(body.get("name") or "").strip()
    if not name or "/" in name or len(name) > 80:
        raise SnmpProfileError("name is required")
    try:
        weight = int(body.get("weight") if body.get("weight") is not None else 100)
    except (TypeError, ValueError):
        raise SnmpProfileError("weight must be an integer")
    scopes = body.get("scopes") if isinstance(body.get("scopes"), dict) else {}
    incoming = body.get("profile") if isinstance(body.get("profile"), dict) else {}
    stored = read_file_profiles(directory)
    previous = stored.get(name) if isinstance(stored.get(name), dict) else {}
    merged = dict(previous)
    merged.update({key: value for key, value in incoming.items() if key not in SECRET_KEYS or str(value or "").strip()})
    for key in SECRET_KEYS:
        if key in incoming and str(incoming.get(key) or "").strip():
            merged[key] = str(incoming[key]).strip()
        elif key not in merged and key in incoming:
            merged.pop(key, None)
    profile = validate_profile(merged)
    profiles = dict(stored)
    profiles[name] = profile
    write_file_profiles(directory, profiles)
    data = build_context_data(profile, mode, name)
    payload: dict[str, Any] = {"name": name, "weight": weight, "data": data, "is_active": True}
    for key in SCOPE_KEYS:
        ids = scopes.get(key) or []
        if not isinstance(ids, list):
            raise SnmpProfileError("scope %s must be a list of ids" % key)
        payload[key] = ids
    context_id = body.get("id")
    if context_id:
        saved = _netbox_json(settings, "PATCH", "/api/extras/config-contexts/%s/" % int(context_id), payload)
    else:
        saved = _netbox_json(settings, "POST", "/api/extras/config-contexts/", payload)
    view = public_view(
        profile, auth=auth_name(profile), source="file" if mode == "file" else "context",
        scopes={key: payload.get(key) or [] for key in SCOPE_KEYS}, weight=weight, name=name,
    )
    view["id"] = saved.get("id") if isinstance(saved, dict) else context_id
    view["profile_name"] = name if mode == "file" else ""
    view["invalid"] = False
    return view


def test_device(settings, device_id: int) -> dict:
    detail = _netbox_json(
        settings, "GET",
        "/api/dcim/devices/%s/?exclude=interfaces,front_ports,rear_ports,console_ports,power_ports,power_outlets" % device_id,
    )
    if not isinstance(detail, dict):
        raise SnmpProfileError("device not found")
    ip = device_ip(detail)
    if not ip:
        return {"ok": False, "error": "device has no primary address"}
    resolved = resolve_device(detail.get("config_context"), os.environ, read_file_profiles(snmp_dir(settings)))
    profile = resolved.get("profile")
    if not profile:
        out = {"ok": False, "error": "no snmp profile", "source": resolved.get("source") or ""}
        if resolved.get("invalid"):
            out["warning"] = "invalid monitoring_snmp: " + str(resolved["invalid"])
        return out
    result = snmp_test(profile, ip, auth=resolved.get("auth") or "")
    result["source"] = resolved.get("source")
    result["auth"] = resolved.get("auth")
    result["address"] = ip
    if resolved.get("invalid"):
        result["warning"] = "invalid monitoring_snmp, tested the .env fallback: " + str(resolved["invalid"])
    return result


def sync_snmp(settings, discovery=None, get_json: Callable[[str], Any] | None = None) -> dict:
    """Pull rendered contexts and refresh generated files. Raises on NetBox failure."""
    directory = snmp_dir(settings)
    if get_json is None:
        def get_json(path: str) -> Any:
            return _netbox_json(settings, "GET", path)
    devices = fetch_devices(get_json)
    rows = iter_resolved(devices, os.environ, read_file_profiles(directory))
    broken = [str(row.get("id")) for row in rows if row["resolved"].get("invalid")]
    if broken:
        log.warning("snmp sync: invalid monitoring_snmp for device ids %s, using the .env fallback", ",".join(broken[:20]))
    base = os.path.join(getattr(settings, "config_root", "") or ".", "snmp", "out", "snmp.yml")
    summary = write_outputs(directory, base, rows)
    if discovery is not None:
        discovery.render_deployment()
    reload_exporters(default_exporter_urls())
    log.info("snmp sync devices=%s profiles=%s mapped=%s", summary["devices"], summary["profiles"], summary["mapped"])
    return summary


def snmp_test(profile: dict, host: str, exporter_get: Callable | None = None, auth: str = "") -> dict:
    """Test one resolved profile against one address. Secrets stay in the request, not the result."""
    port = int(profile.get("port") or 161)
    if profile.get("version") == "2c":
        return snmp_v2c_get(host, profile.get("community") or "", port)
    if exporter_get is None:
        exporter_get = exporter_probe
    # The .env fallback uses a fixed auth name, not the hashed one.
    auth = auth or auth_name(profile)
    try:
        status = exporter_get(host, auth, port)
    except OSError:
        return {"ok": False, "error": "exporter_unreachable", "version": "3"}
    out = {"ok": status == 200, "version": "3", "auth": auth}
    if status == 400:
        # The exporter does not know this auth yet: the runtime file is written by the next sync.
        out["error"] = "auth_not_loaded"
    elif status != 200:
        out["error"] = "no_response"
    return out