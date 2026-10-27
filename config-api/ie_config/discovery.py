"""NetBox prefix selection, sysObjectID guesses, and discovery orchestration.

Network calls are injected so unit tests do not need NetBox, Netdisco or a device.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
from datetime import datetime, timezone

import httpx
import yaml
from sqlalchemy import select

from .db import DiscoveryCandidate, utcnow

_CIDR = re.compile(r"^[0-9]{1,3}(?:\.[0-9]{1,3}){3}/[0-9]{1,2}$")


def valid_cidr(value: str) -> bool:
    if not isinstance(value, str) or not _CIDR.match(value.strip()):
        return False
    try:
        net = ipaddress.ip_network(value.strip(), strict=False)
    except ValueError:
        return False
    return isinstance(net, ipaddress.IPv4Network)


def load_yaml(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError):
        return default
    return default if data is None else data


def select_prefixes(prefixes: list[dict], settings: dict) -> list[str]:
    """Choose which NetBox prefixes become Netdisco discover targets."""
    mode = (settings or {}).get("prefix_selector") or "tag"
    tag = (settings or {}).get("tag") or "ie-scan"
    field = (settings or {}).get("custom_field") or "ie_scan"
    scan_all = bool((settings or {}).get("scan_all_active_prefixes"))
    chosen = []
    for row in prefixes or []:
        cidr = (row.get("prefix") or "").split()[0]
        if not valid_cidr(cidr):
            continue
        status = (row.get("status") or {}).get("value") if isinstance(row.get("status"), dict) else row.get("status")
        if status and status != "active":
            continue
        if scan_all or mode == "all":
            chosen.append(cidr)
            continue
        tags = []
        for t in row.get("tags") or []:
            if isinstance(t, dict):
                tags.append(t.get("slug") or t.get("name") or "")
            else:
                tags.append(str(t))
        custom = row.get("custom_fields") or {}
        if mode == "custom_field":
            if custom.get(field) in (True, "true", "yes", "on", 1):
                chosen.append(cidr)
        else:  # tag
            if tag in tags:
                chosen.append(cidr)
    # stable, unique
    return list(dict.fromkeys(chosen))


def guess_device(sysobjectid: str, sysdescr: str, mapping: dict) -> dict:
    """Guess manufacturer, role, platform and a model string from SNMP identity."""
    oid = (sysobjectid or "").strip()
    descr = sysdescr or ""
    found = {
        "manufacturer": "",
        "manufacturer_slug": "",
        "platform": "",
        "role": (mapping or {}).get("default_role") or "access-switch",
        "model": _model_from_descr(descr),
    }
    for row in (mapping or {}).get("prefixes") or []:
        prefix = str(row.get("oid") or "")
        if prefix and (oid == prefix.rstrip(".") or oid.startswith(prefix)):
            found.update({
                "manufacturer": row.get("manufacturer") or found["manufacturer"],
                "manufacturer_slug": row.get("manufacturer_slug") or _slug(row.get("manufacturer") or ""),
                "platform": row.get("platform") or found["platform"],
                "role": row.get("role") or found["role"],
            })
            break
    for row in (mapping or {}).get("descr_patterns") or []:
        try:
            if row.get("regex") and re.search(row["regex"], descr):
                if row.get("role"):
                    found["role"] = row["role"]
                if row.get("manufacturer"):
                    found["manufacturer"] = row["manufacturer"]
                    found["manufacturer_slug"] = row.get("manufacturer_slug") or _slug(row["manufacturer"])
                if row.get("platform"):
                    found["platform"] = row["platform"]
                break
        except re.error:
            continue
    if not found["manufacturer_slug"] and found["manufacturer"]:
        found["manufacturer_slug"] = _slug(found["manufacturer"])
    if not found["model"]:
        found["model"] = "unknown"
    return found


def _model_from_descr(descr: str) -> str:
    # First useful token of sysDescr, trimmed. Not a full parser.
    text = " ".join((descr or "").split())
    if not text:
        return "unknown"
    return text[:64]


def _slug(value: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return s[:40] or "unknown"


def module_for(role: str, manufacturer: str, platform: str, mapping: dict) -> tuple[str, str]:
    """Return (comma-separated modules, auth name) for a device."""
    mapping = mapping or {}
    by_platform = mapping.get("by_platform") or {}
    by_mfr = mapping.get("by_manufacturer") or {}
    by_role = mapping.get("by_role") or {}
    chosen = None
    if platform and platform in by_platform:
        chosen = by_platform[platform]
    elif manufacturer and manufacturer in by_mfr:
        chosen = by_mfr[manufacturer]
    elif role and role in by_role:
        chosen = by_role[role]
    if not chosen:
        modules = mapping.get("default_module") or "if_mib"
        auth = mapping.get("default_auth") or "ntt_snmpv3_auth"
        return modules, auth
    modules = chosen.get("modules") or chosen.get("module") or mapping.get("default_module") or "if_mib"
    if isinstance(modules, list):
        modules = ",".join(modules)
    auth = chosen.get("auth") or mapping.get("default_auth") or "ntt_snmpv3_auth"
    return modules, auth


def render_template(text: str, env: dict[str, str], allow: set[str]) -> str:
    """Substitute ${NAME} for an allow-list. Unknown placeholders are left as-is."""
    def repl(m):
        name = m.group(1)
        if name in allow and name in env:
            return env[name]
        return m.group(0)
    return re.sub(r"\$\{([A-Z0-9_]+)\}", repl, text)


_SECRET_VARS = {
    "SNMP_V2_COMMUNITY", "SNMP_V3_USER", "SNMP_V3_USERNAME",
    "SNMP_V3_AUTH_PASSWORD", "SNMP_V3_PRIV_PASSWORD",
}


class Discovery:
    def __init__(self, settings, session_factory, config_root: str):
        self.settings = settings
        self.sf = session_factory
        self.config_root = config_root

    def sync_settings_path(self) -> str:
        return os.path.join(self.config_root, "config", "discovery", "sync.yml")

    def module_map_path(self) -> str:
        return os.path.join(self.config_root, "config", "discovery", "module-map.yml")

    def sysobject_path(self) -> str:
        return os.path.join(self.config_root, "config", "discovery", "sysobjectid-map.yml")

    def deployment_template_path(self) -> str:
        return os.path.join(self.config_root, "config", "netdisco", "deployment.yml")

    def read_sync_settings(self) -> dict:
        data = load_yaml(self.sync_settings_path(), {})
        if not isinstance(data, dict):
            data = {}
        data.setdefault("prefix_selector", "tag")
        data.setdefault("tag", "ie-scan")
        data.setdefault("custom_field", "ie_scan")
        data.setdefault("scan_all_active_prefixes", False)
        data.setdefault("interval_hours", 6)
        return data

    def netbox_headers(self) -> dict:
        token = ""
        try:
            with open(self.settings.netbox_token_file, "r", encoding="utf-8") as fh:
                token = fh.read().strip()
        except OSError:
            token = ""
        if not token or token == "unset-placeholder":
            return {}
        if token.startswith("nbt_"):
            return {"Authorization": "Bearer " + token, "Accept": "application/json"}
        return {"Authorization": "Token " + token, "Accept": "application/json"}

    def fetch_prefixes(self) -> list[dict]:
        headers = self.netbox_headers()
        if not headers:
            raise RuntimeError("netbox token is not set")
        url = self.settings.netbox_url + "/api/ipam/prefixes/?limit=500&status=active"
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            body = resp.json()
        return list(body.get("results") or [])

    def fetch_netbox_ips(self) -> set[str]:
        headers = self.netbox_headers()
        if not headers:
            return set()
        url = self.settings.netbox_url + "/api/dcim/devices/?limit=500&status=active"
        ips: set[str] = set()
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            for device in resp.json().get("results") or []:
                primary = device.get("primary_ip4") or {}
                address = primary.get("address") if isinstance(primary, dict) else ""
                if address:
                    ips.add(address.split("/")[0])
        return ips

    def fetch_netdisco_devices(self) -> list[dict]:
        url = self.settings.netdisco_database_url
        if not url:
            return []
        # Imported lazily so unit tests without psycopg still import this module.
        import psycopg
        rows = []
        with psycopg.connect(url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT host(ip)::text, COALESCE(dns, ''), COALESCE(description, ''), "
                    "COALESCE(vendor, ''), COALESCE(model, '') FROM device"
                )
                for ip, dns, descr, vendor, model in cur.fetchall():
                    rows.append({
                        "ip": ip, "name": dns or "", "sysdescr": descr or "",
                        "vendor": vendor or "", "model": model or "", "sysobjectid": "",
                    })
        return rows

    def write_scan_files(self, prefixes: list[str], interval_hours: int) -> None:
        out = self.settings.netdisco_out_dir
        os.makedirs(out, exist_ok=True)
        body = "\n".join(prefixes) + ("\n" if prefixes else "")
        path = os.path.join(out, "scan-prefixes.txt")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(body)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        with open(os.path.join(out, "interval-hours"), "w", encoding="utf-8") as fh:
            fh.write(str(int(interval_hours)))
        self.render_deployment()

    def render_deployment(self) -> None:
        template_path = self.deployment_template_path()
        try:
            with open(template_path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            return
        env = dict(os.environ)
        if env.get("SNMP_V3_USER") and not env.get("SNMP_V3_USERNAME"):
            env["SNMP_V3_USERNAME"] = env["SNMP_V3_USER"]
        rendered = render_template(text, env, _SECRET_VARS)
        out = self.settings.netdisco_out_dir
        os.makedirs(out, exist_ok=True)
        path = os.path.join(out, "deployment.yml")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(rendered)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)

    def request_scan(self) -> None:
        out = self.settings.netdisco_out_dir
        os.makedirs(out, exist_ok=True)
        flag = os.path.join(out, "scan-now")
        with open(flag, "w", encoding="utf-8") as fh:
            fh.write(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    def sync_prefixes(self) -> dict:
        settings = self.read_sync_settings()
        try:
            hours = int(settings.get("interval_hours") or 6)
        except (TypeError, ValueError):
            hours = 6
        hours = min(168, max(1, hours))
        try:
            rows = self.fetch_prefixes()
        except Exception as exc:
            return {"ok": False, "message": "could not read NetBox prefixes: %s" % exc.__class__.__name__, "prefixes": []}
        chosen = select_prefixes(rows, settings)
        self.write_scan_files(chosen, hours)
        return {"ok": True, "message": "wrote %d prefix(es) for Netdisco" % len(chosen), "prefixes": chosen}

    def refresh_unapproved(self) -> dict:
        try:
            known = self.fetch_netbox_ips()
        except Exception:
            known = set()
        try:
            found = self.fetch_netdisco_devices()
        except Exception as exc:
            return {"ok": False, "message": "could not read Netdisco: %s" % exc.__class__.__name__, "added": 0}
        mapping = load_yaml(self.sysobject_path(), {})
        added = 0
        with self.sf() as db:
            for row in found:
                ip = row.get("ip") or ""
                if not ip or ip in known:
                    continue
                existing = db.scalar(select(DiscoveryCandidate).where(DiscoveryCandidate.ip == ip))
                guess = guess_device(row.get("sysobjectid") or "", row.get("sysdescr") or "", mapping)
                if existing is None:
                    db.add(DiscoveryCandidate(
                        ip=ip,
                        name=row.get("name") or ip,
                        sysdescr=row.get("sysdescr") or "",
                        sysobjectid=row.get("sysobjectid") or "",
                        vendor=row.get("vendor") or guess["manufacturer"],
                        model=row.get("model") or guess["model"],
                        status="pending",
                        role_slug=guess["role"],
                        last_seen=utcnow(),
                        detail=json.dumps(guess),
                    ))
                    added += 1
                elif existing.status == "pending":
                    existing.last_seen = utcnow()
                    existing.sysdescr = row.get("sysdescr") or existing.sysdescr
                    existing.vendor = row.get("vendor") or existing.vendor
                    existing.model = row.get("model") or existing.model
            db.commit()
        return {"ok": True, "message": "recorded %d new unapproved device(s)" % added, "added": added}

    def list_unapproved(self) -> list[dict]:
        with self.sf() as db:
            rows = db.scalars(
                select(DiscoveryCandidate).where(DiscoveryCandidate.status == "pending").order_by(DiscoveryCandidate.id)
            ).all()
            return [_public(r) for r in rows]

    def get(self, cid: int) -> DiscoveryCandidate | None:
        with self.sf() as db:
            return db.get(DiscoveryCandidate, cid)

    def set_status(self, cid: int, status: str, netbox_id: str = "", detail: str = "") -> dict | None:
        with self.sf() as db:
            row = db.get(DiscoveryCandidate, cid)
            if row is None:
                return None
            row.status = status
            if netbox_id:
                row.netbox_device_id = netbox_id
            if detail:
                row.detail = detail
            db.commit()
            return _public(row)


def _public(row: DiscoveryCandidate) -> dict:
    return {
        "id": row.id,
        "ip": row.ip,
        "name": row.name,
        "sysDescr": row.sysdescr,
        "sysObjectID": row.sysobjectid,
        "vendor": row.vendor,
        "model": row.model,
        "status": row.status,
        "role": row.role_slug,
        "site": row.site_slug,
        "netboxDeviceId": row.netbox_device_id or None,
        "firstSeen": _iso(row.first_seen),
        "lastSeen": _iso(row.last_seen),
    }


def _iso(value) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


class NetBoxWriter:
    """Creates the objects an approved device needs. Methods are small so tests can fake the client."""

    def __init__(self, base_url: str, headers: dict):
        self.base = base_url.rstrip("/")
        self.headers = dict(headers)
        self.headers["Content-Type"] = "application/json"

    def _req(self, method: str, path: str, body: dict | None = None) -> dict:
        with httpx.Client(timeout=20.0) as client:
            resp = client.request(method, self.base + path, headers=self.headers, json=body)
            if resp.status_code >= 400:
                raise RuntimeError("netbox %s %s -> %s" % (method, path, resp.status_code))
            if resp.content:
                return resp.json()
            return {}

    def ensure(self, list_path: str, slug: str, body: dict) -> dict:
        found = self._req("GET", "%s?slug=%s" % (list_path, slug))
        results = found.get("results") or []
        if results:
            return results[0]
        return self._req("POST", list_path, body)

    def approve_device(self, candidate: dict, guess: dict, sync_settings: dict) -> dict:
        site_slug = candidate.get("site") or sync_settings.get("default_site_slug") or "discovered"
        role_slug = guess.get("role") or sync_settings.get("default_role_slug") or "access-switch"
        mfr_slug = guess.get("manufacturer_slug") or "unknown"
        mfr_name = guess.get("manufacturer") or "Unknown"
        model = (guess.get("model") or "unknown")[:64]
        model_slug = _slug(model)[:40]
        manufacturer = self.ensure("/api/dcim/manufacturers/", mfr_slug, {"name": mfr_name, "slug": mfr_slug})
        dtype = self.ensure("/api/dcim/device-types/", model_slug, {
            "manufacturer": manufacturer["id"], "model": model, "slug": model_slug,
        })
        role = self.ensure("/api/dcim/device-roles/", role_slug, {
            "name": role_slug, "slug": role_slug, "color": "2196f3",
        })
        site = self.ensure("/api/dcim/sites/", site_slug, {
            "name": site_slug, "slug": site_slug, "status": "active",
        })
        name = candidate.get("name") or ("discovered-%s" % candidate["ip"].replace(".", "-"))
        device = self._req("POST", "/api/dcim/devices/", {
            "name": name[:64],
            "device_type": dtype["id"],
            "role": role["id"],
            "site": site["id"],
            "status": "active",
        })
        ip = self._req("POST", "/api/ipam/ip-addresses/", {
            "address": candidate["ip"] + "/32",
            "status": "active",
            "assigned_object_type": "dcim.device",
            "description": "primary address from discovery approval",
        })
        # NetBox wants the IP assigned to an interface before it can be primary.
        iface = self._req("POST", "/api/dcim/interfaces/", {
            "device": device["id"], "name": "mgmt", "type": "virtual",
        })
        self._req("PATCH", "/api/ipam/ip-addresses/%s/" % ip["id"], {
            "assigned_object_type": "dcim.interface",
            "assigned_object_id": iface["id"],
        })
        self._req("PATCH", "/api/dcim/devices/%s/" % device["id"], {"primary_ip4": ip["id"]})
        return {"device_id": device["id"], "name": device.get("name") or name, "role": role_slug, "site": site_slug}
