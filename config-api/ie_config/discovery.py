"""NetBox prefix selection, sysObjectID guesses, and discovery orchestration.

Network calls are injected so unit tests do not need NetBox, Netdisco or a device.
Discovered devices are recorded only in ie-config until a person approves them.
Nothing in this module creates a NetBox device except NetBoxWriter.approve_device.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
import yaml
from sqlalchemy import select

from .db import DiscoveryCandidate, DiscoveryScan, utcnow

_CIDR = re.compile(r"^[0-9]{1,3}(?:\.[0-9]{1,3}){3}/[0-9]{1,2}$")

# Library manufacturer slug InsightEngine already uses (module-map.yml, sysobjectid-map.yml).
_MFR_SLUG = {
    "cisco": "cisco",
    "fortinet": "fortinet",
    "palo alto": "palo-alto",
    "palo alto networks": "palo-alto",
    "palo-alto": "palo-alto",
    "palo-alto-networks": "palo-alto",
}
_MFR_NAME = {
    "cisco": "Cisco",
    "fortinet": "Fortinet",
    "palo-alto": "Palo Alto Networks",
}

# Netdisco runs as uid/gid 901 and reads deployment.yml from DANCER_ENVDIR.
_NETDISCO_UID = 901
_NETDISCO_GID = 901
_CATALOG_TTL = 60.0


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
        parts = (row.get("prefix") or "").split()
        if not parts:
            continue
        cidr = parts[0]
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
    return list(dict.fromkeys(chosen))


def site_name_from_prefix(row: dict) -> str:
    """Site display name on a NetBox prefix.

    NetBox 4.x stores the assignment as scope_type=dcim.site plus scope.
    Older releases used a site object. A region or location scope is not a site.
    """
    site = row.get("site")
    if isinstance(site, dict):
        return (site.get("name") or site.get("slug") or "").strip()
    scope_type = row.get("scope_type") or ""
    if isinstance(scope_type, dict):
        scope_type = scope_type.get("value") or scope_type.get("label") or ""
    if str(scope_type) not in ("dcim.site", "site"):
        return ""
    scope = row.get("scope") or {}
    if not isinstance(scope, dict):
        return ""
    return (scope.get("name") or scope.get("slug") or "").strip()


def _active_prefix(row: dict) -> bool:
    status = row.get("status")
    if isinstance(status, dict):
        status = status.get("value")
    return not status or status == "active"


def site_for_ip(ip: str, prefixes: list[dict]) -> str:
    """Most specific active prefix that contains ip and is scoped to a site."""
    try:
        addr = ipaddress.ip_address((ip or "").split("/")[0])
    except ValueError:
        return ""
    if not isinstance(addr, ipaddress.IPv4Address):
        return ""
    best = ""
    best_len = -1
    for row in prefixes or []:
        if not isinstance(row, dict) or not _active_prefix(row):
            continue
        parts = (row.get("prefix") or "").split()
        if not parts:
            continue
        cidr = parts[0]
        if not valid_cidr(cidr):
            continue
        net = ipaddress.ip_network(cidr, strict=False)
        if addr in net and net.prefixlen >= best_len:
            name = site_name_from_prefix(row)
            if name:
                best = name
                best_len = net.prefixlen
    return best


def ip_in_cidrs(ip: str, cidrs: list[str]) -> bool:
    try:
        addr = ipaddress.ip_address((ip or "").split("/")[0])
    except ValueError:
        return False
    for cidr in cidrs or []:
        if not valid_cidr(cidr):
            continue
        if addr in ipaddress.ip_network(cidr, strict=False):
            return True
    return False


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
    text = " ".join((descr or "").split())
    if not text:
        return "unknown"
    return text[:64]


def _slug(value: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return s[:40] or "unknown"


def manufacturer_identity(vendor: str, guess: dict) -> tuple[str, str]:
    """Return (display name, slug) for a NetBox manufacturer.

    Palo Alto is forced to slug palo-alto so it matches the vendored library
    and the discovery maps. The UI and Netdisco often say "Palo Alto Networks".
    """
    guess = guess or {}
    raw_name = (guess.get("manufacturer") or vendor or "").strip()
    raw_slug = (guess.get("manufacturer_slug") or "").strip().lower()
    key = raw_slug or raw_name.lower()
    slug = _MFR_SLUG.get(key) or _MFR_SLUG.get(raw_name.lower()) or raw_slug or _slug(raw_name)
    name = _MFR_NAME.get(slug) or raw_name or _MFR_NAME.get(slug) or "Unknown"
    if not raw_name and not raw_slug:
        return "Unknown", "unknown"
    if slug == "unknown" and not name:
        return "Unknown", "unknown"
    return name, slug


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
_RENDER_VARS = _SECRET_VARS | {"SNMP_TIMEOUT_US", "SNMP_RETRIES", "SNMP_TRY_SLOW"}


def _bounded_number(value, default: float, lo: float, hi: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number < lo or number > hi:
        return default
    return number


def _read_lines(path: str) -> list[str]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line and valid_cidr(line):
            out.append(str(ipaddress.ip_network(line, strict=False)))
    return list(dict.fromkeys(out))


def _atomic_text(path: str, body: str, mode: int) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(body)
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(tmp, mode)
    os.replace(tmp, path)


class Discovery:
    def __init__(self, settings, session_factory, config_root: str):
        self.settings = settings
        self.sf = session_factory
        self.config_root = config_root
        self._catalog_at = 0.0
        self._catalog: dict | None = None

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
        data.setdefault("prefix_poll_seconds", 60)
        data.setdefault("snmp_timeout_us", 1000000)
        data.setdefault("snmp_retries", 1)
        data.setdefault("snmp_try_slow_connect", False)
        data.setdefault("presweep_timeout_seconds", 0.4)
        data.setdefault("presweep_parallel", 64)
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
        # NetBox 4.5+ v2 tokens are nbt_<key>.<secret> and use Bearer.
        # v1 tokens (deprecated in 4.6) stay on the Token scheme.
        if token.startswith("nbt_"):
            return {"Authorization": "Bearer " + token, "Accept": "application/json"}
        return {"Authorization": "Token " + token, "Accept": "application/json"}

    def _netbox_get_all(self, path: str, timeout: float = 30.0) -> list[dict]:
        headers = self.netbox_headers()
        if not headers:
            raise RuntimeError("netbox token is not set")
        url = self.settings.netbox_url + path
        out: list[dict] = []
        with httpx.Client(timeout=timeout) as client:
            pages = 0
            while url and pages < 50:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
                body = resp.json()
                out.extend(body.get("results") or [])
                url = body.get("next") or ""
                pages += 1
        return out

    def fetch_prefixes(self) -> list[dict]:
        return self._netbox_get_all("/api/ipam/prefixes/?limit=1000&status=active")

    def fetch_netbox_ips(self) -> set[str]:
        """IPs that already belong to a NetBox device (primary or any assigned address)."""
        headers = self.netbox_headers()
        if not headers:
            return set()
        ips: set[str] = set()
        for device in self._netbox_get_all("/api/dcim/devices/?limit=1000&status=active"):
            primary = device.get("primary_ip4") or device.get("primary_ip") or {}
            address = primary.get("address") if isinstance(primary, dict) else ""
            if address:
                ips.add(str(address).split("/")[0])
        return ips

    def ip_assigned_in_netbox(self, ip: str) -> bool:
        headers = self.netbox_headers()
        if not headers or not ip:
            return False
        url = self.settings.netbox_url + "/api/ipam/ip-addresses/?address=" + quote(ip, safe="")
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
                body = resp.json()
        except (httpx.HTTPError, ValueError):
            return False
        for row in body.get("results") or []:
            address = str(row.get("address") or "").split("/")[0]
            if address == ip:
                return True
        return False

    def fetch_netdisco_devices(self) -> list[dict]:
        url = self.settings.netdisco_database_url
        if not url:
            return []
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

    def _out(self, name: str) -> str:
        return os.path.join(self.settings.netdisco_out_dir, name)

    def write_scan_files(self, prefixes: list[str], interval_hours: int) -> None:
        out = self.settings.netdisco_out_dir
        os.makedirs(out, exist_ok=True)
        body = "\n".join(prefixes) + ("\n" if prefixes else "")
        path = os.path.join(out, "scan-prefixes.txt")
        _atomic_text(path, body, 0o644)
        _atomic_text(os.path.join(out, "interval-hours"), str(int(interval_hours)), 0o644)
        self._write_presweep_env(self.read_sync_settings())
        self.render_deployment()

    def _write_presweep_env(self, settings: dict) -> None:
        timeout = _bounded_number(settings.get("presweep_timeout_seconds"), 0.4, 0.05, 5)
        parallel = int(_bounded_number(settings.get("presweep_parallel"), 64, 1, 256))
        # Numbers only. The scheduler reads this file; it must not be executable shell.
        body = "PRESWEEP_TIMEOUT=%s\nPRESWEEP_PARALLEL=%s\n" % (timeout, parallel)
        os.makedirs(self.settings.netdisco_out_dir, exist_ok=True)
        _atomic_text(self._out("presweep.env"), body, 0o644)

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
        sync = self.read_sync_settings()
        timeout_us = int(_bounded_number(sync.get("snmp_timeout_us"), 1000000, 100000, 30000000))
        retries = int(_bounded_number(sync.get("snmp_retries"), 1, 0, 5))
        slow = sync.get("snmp_try_slow_connect")
        env["SNMP_TIMEOUT_US"] = str(timeout_us)
        env["SNMP_RETRIES"] = str(retries)
        env["SNMP_TRY_SLOW"] = "true" if slow in (True, "true", "yes", "on", 1, "1") else "false"
        rendered = render_template(text, env, _RENDER_VARS)
        out = self.settings.netdisco_out_dir
        os.makedirs(out, exist_ok=True)
        path = os.path.join(out, "deployment.yml")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(rendered)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)
        try:
            os.chown(tmp, _NETDISCO_UID, _NETDISCO_GID)
        except OSError:
            # Not root (unit tests, or a manual run). Netdisco still has to be able to read it.
            os.chmod(tmp, 0o644)
        os.replace(tmp, path)
        self._write_presweep_env(sync)

    def request_scan(self) -> None:
        out = self.settings.netdisco_out_dir
        os.makedirs(out, exist_ok=True)
        flag = os.path.join(out, "scan-now")
        with open(flag, "w", encoding="utf-8") as fh:
            fh.write(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        try:
            os.chmod(flag, 0o644)
        except OSError:
            pass

    def sync_prefixes(self) -> dict:
        settings = self.read_sync_settings()
        try:
            hours = int(settings.get("interval_hours") or 6)
        except (TypeError, ValueError):
            hours = 6
        hours = min(168, max(1, hours))
        previous = _read_lines(self._out("scan-prefixes.txt"))
        try:
            rows = self.fetch_prefixes()
        except Exception as exc:
            return {"ok": False, "message": "could not read NetBox prefixes: %s" % exc.__class__.__name__, "prefixes": []}
        chosen = select_prefixes(rows, settings)
        removed = [cidr for cidr in previous if cidr not in set(chosen)]
        os.makedirs(self.settings.netdisco_out_dir, exist_ok=True)
        _atomic_text(self._out("scan-prefixes.removed"), ("\n".join(removed) + ("\n" if removed else "")), 0o644)
        dropped = self._drop_pending_in_removed(removed, chosen)
        self.write_scan_files(chosen, hours)
        changed = set(previous) != set(chosen)
        if changed:
            # A new or removed prefix should be picked up by the scheduler within a minute,
            # not on the next multi-hour discover interval.
            self.request_scan()
        return {
            "ok": True,
            "message": "wrote %d prefix(es) for Netdisco" % len(chosen),
            "prefixes": chosen,
            "removed": removed,
            "dropped": dropped,
            "changed": changed,
        }

    def _drop_pending_in_removed(self, removed: list[str], current: list[str]) -> int:
        """Drop still-pending candidates that lived only in a prefix we stopped scanning."""
        if not removed:
            return 0
        dropped = 0
        with self.sf() as db:
            rows = db.scalars(
                select(DiscoveryCandidate).where(DiscoveryCandidate.status == "pending")
            ).all()
            for row in rows:
                if ip_in_cidrs(row.ip, removed) and not ip_in_cidrs(row.ip, current):
                    db.delete(row)
                    dropped += 1
            db.commit()
        return dropped

    def _eligible(self, ip: str) -> bool:
        current = _read_lines(self._out("scan-prefixes.txt"))
        manual = _read_lines(self._out("manual-targets.txt"))
        removed = _read_lines(self._out("scan-prefixes.removed"))
        if ip_in_cidrs(ip, current):
            return True
        if ip_in_cidrs(ip, manual) and not ip_in_cidrs(ip, removed):
            return True
        return False

    def refresh_unapproved(self) -> dict:
        try:
            known = self.fetch_netbox_ips()
        except Exception:
            known = set()
        try:
            found = self.fetch_netdisco_devices()
        except Exception as exc:
            return {"ok": False, "message": "could not read Netdisco: %s" % exc.__class__.__name__, "added": 0}
        try:
            prefixes = self.fetch_prefixes()
        except Exception:
            prefixes = []
        mapping = load_yaml(self.sysobject_path(), {})
        added = 0
        removed = 0
        with self.sf() as db:
            pending_ips = {
                row.ip for row in db.scalars(
                    select(DiscoveryCandidate).where(DiscoveryCandidate.status == "pending")
                ).all()
            }
        for ip in pending_ips:
            if ip not in known and self.ip_assigned_in_netbox(ip):
                known.add(ip)
        with self.sf() as db:
            seen: set[str] = set()
            for row in found:
                ip = row.get("ip") or ""
                if not ip or ip in seen:
                    continue
                seen.add(ip)
                existing = db.scalar(select(DiscoveryCandidate).where(DiscoveryCandidate.ip == ip))
                if ip in known or not self._eligible(ip):
                    if existing is not None and existing.status == "pending":
                        db.delete(existing)
                        removed += 1
                    continue
                guess = guess_device(row.get("sysobjectid") or "", row.get("sysdescr") or "", mapping)
                site = site_for_ip(ip, prefixes)
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
                        site_slug=site,
                        last_seen=utcnow(),
                        detail=json.dumps(guess),
                    ))
                    added += 1
                elif existing.status == "pending":
                    existing.last_seen = utcnow()
                    existing.sysdescr = row.get("sysdescr") or existing.sysdescr
                    existing.vendor = row.get("vendor") or existing.vendor
                    existing.model = row.get("model") or existing.model
                    if site and not (existing.site_slug or "").strip():
                        existing.site_slug = site
                    if guess.get("role") and not (existing.role_slug or "").strip():
                        existing.role_slug = guess["role"]
                    existing.detail = json.dumps(guess)
            # Pending rows Netdisco no longer returns, once the address exists in NetBox
            # or the prefix that contained them was removed.
            for row in db.scalars(select(DiscoveryCandidate).where(DiscoveryCandidate.status == "pending")).all():
                if row.ip in seen:
                    continue
                if row.ip in known or not self._eligible(row.ip):
                    db.delete(row)
                    removed += 1
            db.commit()
        return {
            "ok": True,
            "message": "recorded %d new unapproved device(s)" % added,
            "added": added,
            "removed": removed,
        }

    def _fill_missing_sites(self) -> None:
        with self.sf() as db:
            rows = db.scalars(
                select(DiscoveryCandidate).where(DiscoveryCandidate.status == "pending")
            ).all()
            if not any(not (row.site_slug or "").strip() for row in rows):
                return
        try:
            prefixes = self.fetch_prefixes()
        except Exception:
            return
        with self.sf() as db:
            rows = db.scalars(
                select(DiscoveryCandidate).where(DiscoveryCandidate.status == "pending")
            ).all()
            changed = False
            for row in rows:
                if (row.site_slug or "").strip():
                    continue
                site = site_for_ip(row.ip, prefixes)
                if site:
                    row.site_slug = site
                    changed = True
            if changed:
                db.commit()

    def queue_manual_scan(self, target: str, value: str) -> dict:
        """Queue one prefix or address for the Netdisco scheduler and remember it."""
        kind = (target or "").strip()
        raw = (value or "").strip()
        if kind == "ip":
            if "/" in raw or not valid_cidr(raw + "/32"):
                raise ValueError("Enter an IPv4 address.")
            cidr = str(ipaddress.ip_network(raw + "/32", strict=False))
            message = "Queued a probe of that address. If it answers and is not in NetBox, it will show up here after the next discovery refresh."
        elif kind == "prefix":
            if not valid_cidr(raw):
                raise ValueError("Enter an IPv4 prefix, for example 10.22.14.0/24.")
            cidr = str(ipaddress.ip_network(raw, strict=False))
            message = "Queued a Netdisco walk of that prefix. Devices that are not in NetBox will show up here after the next discovery refresh."
        else:
            raise ValueError("Target must be ip or prefix.")
        out = self.settings.netdisco_out_dir
        os.makedirs(out, exist_ok=True)
        path = os.path.join(out, "scan-once.txt")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(cidr + "\n")
        manual = os.path.join(out, "manual-targets.txt")
        existing = _read_lines(manual)
        if cidr not in existing:
            _atomic_text(manual, "\n".join(existing + [cidr]) + "\n", 0o644)
        self.request_scan()
        with self.sf() as db:
            row = DiscoveryScan(target=kind, value=raw, status="queued", message=message, started_at=utcnow())
            db.add(row)
            db.commit()
            db.refresh(row)
            return _scan_public(row)

    def list_scans(self) -> list[dict]:
        with self.sf() as db:
            rows = db.scalars(select(DiscoveryScan).order_by(DiscoveryScan.id.desc()).limit(20)).all()
            return [_scan_public(row) for row in rows]

    def list_unapproved(self) -> list[dict]:
        self._fill_missing_sites()
        with self.sf() as db:
            rows = db.scalars(
                select(DiscoveryCandidate).where(DiscoveryCandidate.status == "pending").order_by(DiscoveryCandidate.id)
            ).all()
            return [_public(r) for r in rows]

    def catalog(self) -> dict:
        """Device roles, sites and platforms for the approve form. Cached for a minute."""
        now = time.monotonic()
        if self._catalog is not None and (now - self._catalog_at) < _CATALOG_TTL:
            return dict(self._catalog)
        empty = {"ok": False, "roles": [], "sites": [], "platforms": []}
        if not self.netbox_headers():
            return empty
        try:
            roles = self._netbox_get_all("/api/dcim/device-roles/?limit=200")
            sites = self._netbox_get_all("/api/dcim/sites/?limit=1000")
            platforms = self._netbox_get_all("/api/dcim/platforms/?limit=500")
        except Exception:
            return empty
        body = {
            "ok": True,
            "roles": _names(roles),
            "sites": _names(sites),
            "platforms": _names(platforms),
        }
        self._catalog = body
        self._catalog_at = now
        return dict(body)

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


def _names(rows: list[dict]) -> list[str]:
    found = []
    for row in rows or []:
        name = (row.get("name") or row.get("slug") or "").strip()
        if name and name not in found:
            found.append(name)
    return found


def _scan_public(row: DiscoveryScan) -> dict:
    def iso(value):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")

    body = {
        "id": str(row.id),
        "target": row.target,
        "value": row.value,
        "status": row.status,
        "startedAt": iso(row.started_at) or "",
        "message": row.message or "",
    }
    finished = iso(row.finished_at)
    if finished:
        body["finishedAt"] = finished
    return body


def unapproved_for_ui(row: dict) -> dict:
    """Shape GET /api/v1/discovery/unapproved the way the Not in NetBox screen reads it."""
    name = str(row.get("name") or "")
    suggested = {}
    if row.get("role"):
        suggested["role"] = row["role"]
    if row.get("site"):
        suggested["site"] = row["site"]
    if row.get("platform"):
        suggested["platform"] = row["platform"]
    return {
        "id": str(row.get("id")),
        "ip": row.get("ip") or "",
        "hostname": name,
        "sysName": name,
        "vendor": row.get("vendor") or "",
        "model": row.get("model") or "",
        "sysDescr": row.get("sysDescr") or "",
        "firstSeen": row.get("firstSeen") or "",
        "lastSeen": row.get("lastSeen") or "",
        "suggested": suggested,
    }


def _public(row: DiscoveryCandidate) -> dict:
    platform = ""
    try:
        detail = json.loads(row.detail or "{}")
    except ValueError:
        detail = {}
    if isinstance(detail, dict):
        platform = str(detail.get("platform") or "")
    body = {
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
    if platform:
        body["platform"] = platform
    return body


def _iso(value) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


class NetBoxWriter:
    """Creates the objects an approved device needs. Methods are small so tests can fake the client.

    approve_device is the only place a discovered device is written to NetBox.
    """

    def __init__(self, base_url: str, headers: dict):
        self.base = base_url.rstrip("/")
        self.headers = dict(headers)
        self.headers["Content-Type"] = "application/json"

    def _req(self, method: str, path: str, body: dict | list | None = None) -> dict:
        with httpx.Client(timeout=20.0) as client:
            resp = client.request(method, self.base + path, headers=self.headers, json=body)
            if resp.status_code >= 400:
                raise RuntimeError("netbox %s %s -> %s" % (method, path, resp.status_code))
            if resp.content:
                data = resp.json()
                return data if isinstance(data, dict) else {"results": data}
            return {}

    def ensure(self, list_path: str, slug: str, body: dict) -> dict:
        found = self._req("GET", "%s?slug=%s" % (list_path, quote(slug, safe="")))
        results = found.get("results") or []
        if results:
            return results[0]
        return self._req("POST", list_path, body)

    def find_device_type(self, manufacturer_id: int, model: str) -> dict | None:
        """Reuse a device type that already exists (for example from the preloaded library)."""
        if not model or model.lower() == "unknown":
            return None
        encoded = quote(model, safe="")
        for key in ("model", "part_number"):
            res = self._req(
                "GET",
                "/api/dcim/device-types/?manufacturer_id=%s&%s=%s" % (manufacturer_id, key, encoded),
            ).get("results") or []
            if len(res) == 1:
                return res[0]
        res = self._req(
            "GET",
            "/api/dcim/device-types/?manufacturer_id=%s&q=%s&limit=2" % (manufacturer_id, encoded),
        ).get("results") or []
        return res[0] if len(res) == 1 else None

    def approve_device(self, candidate: dict, guess: dict, sync_settings: dict) -> dict:
        # The UI sends names ("Access switch", "Test Site"); NetBox slugs are lower-case with dashes.
        site_name = (candidate.get("site") or sync_settings.get("default_site_slug") or "discovered").strip()
        site_slug = _slug(site_name)
        role_name = (guess.get("role") or sync_settings.get("default_role_slug") or "access-switch").strip()
        role_slug = _slug(role_name)
        mfr_name, mfr_slug = manufacturer_identity(candidate.get("vendor") or "", guess)
        model = (guess.get("model") or "unknown")[:64]
        if (candidate.get("model") or "").strip():
            model = candidate["model"].strip()[:64]
        manufacturer = self.ensure("/api/dcim/manufacturers/", mfr_slug, {"name": mfr_name, "slug": mfr_slug})
        dtype = self.find_device_type(manufacturer["id"], model)
        if dtype is None:
            model_slug = _slug(model)[:40]
            dtype = self.ensure("/api/dcim/device-types/", model_slug, {
                "manufacturer": manufacturer["id"], "model": model, "slug": model_slug,
            })
        role = self.ensure("/api/dcim/device-roles/", role_slug, {
            "name": role_name, "slug": role_slug, "color": "2196f3",
        })
        site = self.ensure("/api/dcim/sites/", site_slug, {
            "name": site_name, "slug": site_slug, "status": "active",
        })
        platform_name = (guess.get("platform") or "").strip()
        platform_id = None
        platform_slug = ""
        if platform_name:
            platform_slug = _slug(platform_name)
            platform = self.ensure("/api/dcim/platforms/", platform_slug, {
                "name": platform_name,
                "slug": platform_slug,
                "manufacturer": manufacturer["id"],
            })
            platform_id = platform.get("id")
        name = candidate.get("name") or ("discovered-%s" % candidate["ip"].replace(".", "-"))
        device_body = {
            "name": name[:64],
            "device_type": dtype["id"],
            "role": role["id"],
            "site": site["id"],
            "status": "active",
        }
        if platform_id:
            device_body["platform"] = platform_id
        device = self._req("POST", "/api/dcim/devices/", device_body)
        try:
            iface = self._req("POST", "/api/dcim/interfaces/", {
                "device": device["id"], "name": "mgmt", "type": "virtual",
            })
            # NetBox needs assigned_object_id together with assigned_object_type, so the interface comes first.
            ip = self._req("POST", "/api/ipam/ip-addresses/", {
                "address": candidate["ip"] + "/32",
                "status": "active",
                "assigned_object_type": "dcim.interface",
                "assigned_object_id": iface["id"],
                "description": "primary address from discovery approval",
            })
            self._req("PATCH", "/api/dcim/devices/%s/" % device["id"], {"primary_ip4": ip["id"]})
        except Exception:
            # Do not leave a half-made device in NetBox (it would show up in /api/v1/devices).
            try:
                self._req("DELETE", "/api/dcim/devices/%s/" % device["id"])
            except Exception:
                pass
            raise
        return {
            "device_id": device["id"],
            "name": device.get("name") or name,
            "role": role_slug,
            "site": site_slug,
            "platform": platform_slug,
        }
