"""NetBox prefix selection, sysObjectID guesses, and discovery orchestration.

Network calls are injected so unit tests do not need NetBox, Netdisco or a device.
Discovered devices are recorded only in ie-config until a person approves them.
Nothing in this module creates a NetBox device except NetBoxWriter.approve_device.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
import yaml
from sqlalchemy import select

from .db import DiscoveryCandidate, DiscoveryDeviceJob, DiscoveryScan, utcnow
from .hostnames import effective_suffixes, inject_domain_suffix, strip_hostname

log = logging.getLogger("ie.discovery")

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


def _ipv4_address(value: str) -> str:
    text = (value or "").strip().split("/")[0].strip()
    parts = text.split(".")
    if len(parts) != 4:
        return ""
    try:
        if all(0 <= int(part) <= 255 and str(int(part)) == part for part in parts):
            return text
    except ValueError:
        return ""
    return ""


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

    def hostname_suffixes(self) -> list[str]:
        return effective_suffixes(self.settings, self.read_sync_settings())

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
        ips, _ids = self.fetch_netbox_presence()
        return ips

    def fetch_netbox_ids(self) -> set[str]:
        _ips, ids = self.fetch_netbox_presence()
        return ids

    def fetch_netbox_presence(self) -> tuple[set[str], set[str]]:
        """Primary IPs and device ids currently in NetBox."""
        cached = getattr(self, "_presence", None)
        stamp = getattr(self, "_presence_at", 0.0)
        if cached is not None and time.monotonic() - stamp < 5:
            return cached
        headers = self.netbox_headers()
        if not headers:
            raise RuntimeError("netbox token is not set")
        ips: set[str] = set()
        ids: set[str] = set()
        for device in self._netbox_get_all("/api/dcim/devices/?limit=1000&status=active"):
            ident = device.get("id")
            if ident is not None:
                ids.add(str(ident))
            primary = device.get("primary_ip4") or device.get("primary_ip") or {}
            address = primary.get("address") if isinstance(primary, dict) else ""
            if address:
                ips.add(str(address).split("/")[0])
        self._presence = (ips, ids)
        self._presence_at = time.monotonic()
        return ips, ids

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
                    "SELECT host(ip)::text, COALESCE(name, ''), COALESCE(dns, ''), "
                    "COALESCE(description, ''), COALESCE(vendor, ''), COALESCE(model, '') FROM device"
                )
                for ip, sysname, dns, descr, vendor, model in cur.fetchall():
                    hostname = (sysname or "").strip() or (dns or "").strip()
                    rows.append({
                        "ip": ip, "name": hostname, "sysdescr": descr or "",
                        "vendor": vendor or "", "model": model or "", "sysobjectid": "",
                    })
                chassis: dict[str, str] = {}
                try:
                    cur.execute(
                        "SELECT host(ip)::text, COALESCE(model, '') FROM device_module "
                        "WHERE class = 'chassis' AND COALESCE(model, '') <> '' ORDER BY index"
                    )
                    for ip, part in cur.fetchall():
                        chassis.setdefault(str(ip).split("/")[0], str(part or ""))
                except Exception:
                    log.warning("netdisco chassis part numbers could not be read")
        for row in rows:
            part = chassis.get(row["ip"]) or ""
            if part:
                row["part"] = part
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
        rendered = inject_domain_suffix(rendered, self.hostname_suffixes())
        rendered = self._splice_snmp_profiles(rendered)
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
        self._maybe_reload_backend(path)

    def _splice_snmp_profiles(self, rendered: str) -> str:
        """Add per-profile device_auth before the .env fallback. No-op when nothing was resolved."""
        from .snmp_sync import ASSIGNMENTS_NAME, netdisco_yaml_entries, read_json, snmp_dir, splice_device_auth
        path = os.path.join(snmp_dir(self.settings), ASSIGNMENTS_NAME)
        data = read_json(path, {})
        groups = data.get("groups") if isinstance(data, dict) else None
        if not groups:
            return rendered
        normalized = []
        for group in groups:
            if not isinstance(group, dict) or not group.get("ips"):
                continue
            profile = {key: value for key, value in group.items() if key not in ("auth", "ips", "source")}
            normalized.append({"auth": group.get("auth") or "ie_snmp", "ips": group["ips"], "profile": profile})
        extra = netdisco_yaml_entries(normalized)
        return splice_device_auth(rendered, extra)

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
        netbox_ok = True
        try:
            known = self.fetch_netbox_ips()
        except Exception:
            known = set()
            netbox_ok = False
        netbox_ids: set[str] = set()
        if netbox_ok:
            try:
                netbox_ids = self.fetch_netbox_ids()
            except Exception:
                netbox_ids = set()
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
                if (
                    netbox_ok
                    and existing is not None
                    and existing.status == "approved"
                    and not (existing.netbox_device_id and str(existing.netbox_device_id) in netbox_ids)
                ):
                    # Approved, then deleted in NetBox. Rediscover can add it again.
                    existing.status = "pending"
                    existing.netbox_device_id = ""
                guess = guess_device(row.get("sysobjectid") or "", row.get("sysdescr") or "", mapping)
                site = site_for_ip(ip, prefixes)
                short_name = strip_hostname(row.get("name") or "", self.hostname_suffixes())
                part = catalog_part(row.get("part") or "")
                family = (row.get("model") or "").strip()
                model_name = part or family or guess["model"]
                if existing is None:
                    db.add(DiscoveryCandidate(
                        ip=ip,
                        name=short_name or ip,
                        sysdescr=row.get("sysdescr") or "",
                        sysobjectid=row.get("sysobjectid") or "",
                        vendor=row.get("vendor") or guess["manufacturer"],
                        model=model_name,
                        status="pending",
                        role_slug=guess["role"],
                        site_slug=site,
                        last_seen=utcnow(),
                        detail=json.dumps(guess),
                    ))
                    added += 1
                elif existing.status == "pending":
                    existing.last_seen = utcnow()
                    if short_name:
                        existing.name = short_name
                    existing.sysdescr = row.get("sysdescr") or existing.sysdescr
                    existing.vendor = row.get("vendor") or existing.vendor
                    if part:
                        existing.model = part
                    elif family and not (existing.model or "").strip():
                        existing.model = family
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
        """Queue one prefix or address for the Netdisco scheduler and remember it.

        A single address is written to scan-once only. Touching scan-now would
        make the scheduler walk every prefix before that address.
        """
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
        with self.sf() as db:
            row = DiscoveryScan(target=kind, value=raw, status="queued", message=message, started_at=utcnow())
            db.add(row)
            db.commit()
            db.refresh(row)
            public = _scan_public(row)
            scan_id = row.id
        out = self.settings.netdisco_out_dir
        os.makedirs(out, exist_ok=True)
        path = os.path.join(out, "scan-once.txt")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("%s %s\n" % (scan_id, cidr))
        self._remember_manual(cidr)
        if kind == "prefix":
            self.request_scan()
        return public

    def _remember_manual(self, cidr: str) -> None:
        out = self.settings.netdisco_out_dir
        os.makedirs(out, exist_ok=True)
        manual = os.path.join(out, "manual-targets.txt")
        existing = _read_lines(manual)
        if cidr not in existing:
            _atomic_text(manual, "\n".join(existing + [cidr]) + "\n", 0o644)

    def alias_path(self) -> str:
        return os.path.join(self.config_root, "config", "discovery", "device-type-aliases.yml")

    def _maybe_reload_backend(self, path: str) -> None:
        """Restart netdisco-backend when deployment.yml actually changed.

        The backend parent watches DANCER_ENVDIR and restarts its worker when
        that file changes, but inotify usually misses a write from another
        container. The ie-config docker proxy allows restart and blocks exec,
        so a restart is how new device_auth is loaded. Unchanged renders do
        not restart the daemon.
        """
        try:
            with open(path, "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()
        except OSError:
            return
        stamp = self._out("deployment.applied")
        previous = ""
        try:
            with open(stamp, "r", encoding="utf-8") as fh:
                previous = fh.read().strip()
        except OSError:
            previous = ""
        if previous == digest:
            return
        if self._reload_backend():
            try:
                _atomic_text(stamp, digest + "\n", 0o644)
            except OSError:
                pass

    def _reload_backend(self) -> bool:
        fn = getattr(self, "restart_backend", None)
        if callable(fn):
            try:
                return bool(fn())
            except Exception as exc:
                log.warning("netdisco-backend restart failed: %s", exc.__class__.__name__)
                return False
        return self._restart_via_proxy()

    def _restart_via_proxy(self) -> bool:
        url = (self.settings.docker_proxy_url or "").rstrip("/")
        slug = self.settings.client_slug or ""
        if not url or not slug or slug == "unconfigured":
            return False
        name = "netdisco-backend-" + slug
        try:
            with httpx.Client(timeout=40.0) as client:
                resp = client.post("%s/containers/%s/restart?t=20" % (url, name))
            if resp.status_code in (200, 204):
                log.info("restarted %s so it reloads device_auth", name)
                return True
            log.warning("netdisco-backend restart -> %s", resp.status_code)
        except Exception as exc:
            log.warning("netdisco-backend restart failed: %s", exc.__class__.__name__)
        return False

    def prepare_device_auth(self) -> None:
        """Refresh SNMP assignments and rewrite deployment.yml before a discover."""
        try:
            sync = getattr(self, "_snmp_sync", None)
            if sync is None:
                from .snmp_sync import sync_snmp
                sync_snmp(self.settings, self)
            else:
                sync()
        except Exception as exc:
            log.warning("snmp sync before device discover failed: %s", exc.__class__.__name__)
        self.render_deployment()

    def _env_snmp_candidates(self) -> list[dict]:
        from .snmp_profiles import ENV_V2_AUTH, ENV_V3_AUTH, SnmpProfileError, validate_profile
        env = os.environ
        found = []
        community = (env.get("SNMP_V2_COMMUNITY") or "").strip()
        if community and community != "unset-placeholder":
            try:
                found.append({
                    "label": "default",
                    "auth": ENV_V2_AUTH,
                    "profile": validate_profile({"version": "2c", "port": 161, "community": community}),
                })
            except SnmpProfileError:
                pass
        user = (env.get("SNMP_V3_USERNAME") or env.get("SNMP_V3_USER") or "").strip()
        auth_pass = (env.get("SNMP_V3_AUTH_PASSWORD") or "").strip()
        priv_pass = (env.get("SNMP_V3_PRIV_PASSWORD") or "").strip()
        if user and user != "unset-placeholder" and auth_pass and auth_pass != "unset-placeholder":
            raw = {
                "version": "3",
                "port": 161,
                "security_name": user,
                "security_level": "authPriv" if priv_pass and priv_pass != "unset-placeholder" else "authNoPriv",
                "auth_protocol": "SHA",
                "auth_passphrase": auth_pass,
            }
            if priv_pass and priv_pass != "unset-placeholder":
                raw["priv_protocol"] = "AES"
                raw["priv_passphrase"] = priv_pass
            try:
                found.append({
                    "label": "default-v3",
                    "auth": ENV_V3_AUTH,
                    "profile": validate_profile(raw),
                })
            except SnmpProfileError:
                pass
        return found

    def profiles_for_ip(self, ip: str) -> list[dict]:
        """Profiles Netdisco would try for this address. Labels are auth names, never secrets."""
        from .snmp_profiles import SnmpProfileError, validate_profile
        from .snmp_sync import ASSIGNMENTS_NAME, read_json, snmp_dir
        found = []
        path = os.path.join(snmp_dir(self.settings), ASSIGNMENTS_NAME)
        data = read_json(path, {})
        groups = data.get("groups") if isinstance(data, dict) else None
        for group in groups or []:
            if not isinstance(group, dict):
                continue
            ips = [str(item).split("/")[0] for item in (group.get("ips") or [])]
            if ip not in ips:
                continue
            raw = {key: value for key, value in group.items() if key not in ("auth", "ips", "source")}
            try:
                profile = validate_profile(raw)
            except SnmpProfileError:
                continue
            label = str(group.get("auth") or "profile")
            found.append({"label": label, "auth": label, "profile": profile})
        found.extend(self._env_snmp_candidates())
        return found

    def snmp_precheck(self, ip: str, probe=None) -> dict:
        """One quick SNMP get. The result names the profile and never includes a secret."""
        from .snmp_sync import snmp_test
        profiles = self.profiles_for_ip(ip)
        if not profiles:
            return {"ok": False, "profile": "", "message": "No SNMP credentials are configured."}

        def default_probe(profile, host, auth):
            return snmp_test(profile, host, auth=auth)

        probe = probe or getattr(self, "_probe", None) or default_probe
        errors = []
        for item in profiles:
            try:
                result = probe(item["profile"], ip, item["auth"])
            except Exception:
                result = {"ok": False, "error": "error"}
            if not isinstance(result, dict):
                result = {"ok": False, "error": "error"}
            if result.get("ok"):
                return {
                    "ok": True,
                    "profile": item["label"],
                    "message": "SNMP reachable via profile %s" % item["label"],
                }
            errors.append("%s: %s" % (item["label"], _snmp_error_text(result.get("error"))))
        return {"ok": False, "profile": "", "message": "SNMP check failed. " + "; ".join(errors)}

    def _admin(self, jobs=None):
        if jobs is not None:
            return jobs
        injected = getattr(self, "_jobs", None)
        if injected is not None:
            return injected
        url = self.settings.netdisco_database_url or ""
        if not url:
            return None
        from .netdisco_jobs import NetdiscoAdmin
        return NetdiscoAdmin(url)

    def _active_device_job(self, ip: str) -> DiscoveryDeviceJob | None:
        with self.sf() as db:
            return db.scalar(
                select(DiscoveryDeviceJob)
                .where(DiscoveryDeviceJob.ip == ip)
                .where(DiscoveryDeviceJob.status.in_(("queued", "running")))
                .order_by(DiscoveryDeviceJob.id.desc())
            )

    def start_device_discover(self, ip: str, neighbours: bool = False, username: str = "insightengine", userip: str | None = None, probe=None, jobs=None) -> dict:
        """SNMP-check one address, then queue Netdisco discover. macsuck and arpnip follow."""
        addr = _ipv4_host(ip)
        active = self._active_device_job(addr)
        if active is not None:
            return self.device_job_status(active.id, jobs=jobs)
        self.prepare_device_auth()
        checked = self.snmp_precheck(addr, probe=probe)
        if not checked["ok"]:
            return self._save_device_job(addr, neighbours, "error", checked["message"], {"snmp": {"status": "error", "message": checked["message"], "profile": ""}})
        admin = self._admin(jobs)
        if admin is None:
            raise RuntimeError("netdisco database is not configured")
        self._remember_manual(str(ipaddress.ip_network(addr + "/32", strict=False)))
        queued = admin.enqueue(addr, "discover", username or "insightengine", _userip(userip))
        detail = {"snmp": {"status": "done", "message": checked["message"], "profile": checked.get("profile") or ""}}
        with self.sf() as db:
            row = DiscoveryDeviceJob(
                ip=addr,
                neighbours=1 if neighbours else 0,
                status="queued",
                message=checked["message"],
                discover_job=int(queued["id"]),
                detail=json.dumps(detail),
                started_at=utcnow(),
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            job_id = row.id
        return self.device_job_status(job_id, jobs=admin)

    def _save_device_job(self, ip: str, neighbours: bool, status: str, message: str, detail: dict) -> dict:
        with self.sf() as db:
            row = DiscoveryDeviceJob(
                ip=ip,
                neighbours=1 if neighbours else 0,
                status=status,
                message=message,
                detail=json.dumps(detail),
                started_at=utcnow(),
                finished_at=utcnow() if status in ("done", "error") else None,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return _device_public(row, _steps_from_detail(detail, status), status, message)

    def device_job_status(self, job_id: int | None = None, ip: str | None = None, jobs=None) -> dict | None:
        admin = self._admin(jobs)
        with self.sf() as db:
            row = None
            if job_id:
                row = db.get(DiscoveryDeviceJob, int(job_id))
            elif ip:
                addr = _ipv4_host(ip)
                row = db.scalar(
                    select(DiscoveryDeviceJob).where(DiscoveryDeviceJob.ip == addr).order_by(DiscoveryDeviceJob.id.desc())
                )
            if row is None:
                return None
            if row.status in ("done", "error") and row.finished_at is not None:
                detail = _load_detail(row.detail)
                saved = detail.get("final_steps")
                if isinstance(saved, list) and saved:
                    return _device_public(row, saved, row.status, row.message or "")
            body, refresh = self._advance(db, row, admin)
            db.commit()
        if refresh:
            try:
                self.refresh_unapproved()
            except Exception as exc:
                log.warning("refresh after discover failed: %s", exc.__class__.__name__)
        return body

    def device_job_by_ip(self, ip: str, jobs=None) -> dict | None:
        return self.device_job_status(ip=ip, jobs=jobs)

    def advance_device_jobs(self) -> int:
        """Move queued device jobs forward. Called from the discovery loop and from GET."""
        admin = self._admin()
        if admin is None:
            return 0
        with self.sf() as db:
            ids = [
                row.id for row in db.scalars(
                    select(DiscoveryDeviceJob).where(DiscoveryDeviceJob.status.in_(("queued", "running")))
                ).all()
            ]
        moved = 0
        for job_id in ids:
            try:
                before = None
                with self.sf() as db:
                    row = db.get(DiscoveryDeviceJob, job_id)
                    before = row.status if row else None
                current = self.device_job_status(job_id, jobs=admin)
                if current and current.get("status") != before:
                    moved += 1
            except Exception as exc:
                log.warning("device job %s: %s", job_id, exc.__class__.__name__)
        return moved

    def _advance(self, db, row: DiscoveryDeviceJob, admin) -> tuple[dict, bool]:
        detail = _load_detail(row.detail)
        snmp = detail.get("snmp") if isinstance(detail.get("snmp"), dict) else {}
        snmp_status = snmp.get("status") or "done"
        snmp_message = str(snmp.get("message") or "")
        steps = [{"name": "snmp", "status": snmp_status, "message": snmp_message}]
        if snmp_status == "error":
            steps.extend([
                {"name": "discover", "status": "error", "message": "Not started."},
                {"name": "macsuck", "status": "error", "message": "Not started."},
                {"name": "arpnip", "status": "error", "message": "Not started."},
            ])
            row.status = "error"
            row.message = snmp_message or "SNMP check failed."
            if row.finished_at is None:
                row.finished_at = utcnow()
            detail["final_steps"] = steps
            row.detail = json.dumps(detail)
            return _device_public(row, steps, "error", row.message), False
        if admin is None:
            raise RuntimeError("netdisco database is not configured")
        discover = _step_from_admin(admin, row.discover_job, "discover")
        if discover["status"] == "done" and not row.macsuck_job:
            mac = admin.enqueue(row.ip, "macsuck", "insightengine", None)
            arp = admin.enqueue(row.ip, "arpnip", "insightengine", None)
            row.macsuck_job = int(mac["id"])
            row.arpnip_job = int(arp["id"])
        if discover["status"] == "done":
            if row.macsuck_job:
                admin.release_skipped(row.ip, "macsuck")
            if row.arpnip_job:
                admin.release_skipped(row.ip, "arpnip")
        if discover["status"] == "done" and row.neighbours and not detail.get("neighbours_enqueued"):
            neighbour_jobs = []
            for raw_ip in admin.neighbour_ips(row.ip):
                try:
                    nip = _ipv4_host(raw_ip)
                except ValueError:
                    continue
                if nip == row.ip:
                    continue
                queued = admin.enqueue(nip, "discover", "insightengine", None)
                neighbour_jobs.append({"ip": nip, "id": int(queued["id"])})
                self._remember_manual(str(ipaddress.ip_network(nip + "/32", strict=False)))
            detail["neighbours_enqueued"] = True
            detail["neighbour_jobs"] = neighbour_jobs
        if discover["status"] == "error":
            macsuck = {"name": "macsuck", "status": "error", "message": "Not started because discover failed."}
            arpnip = {"name": "arpnip", "status": "error", "message": "Not started because discover failed."}
        else:
            waiting = discover["status"] != "done"
            macsuck = _step_from_admin(admin, row.macsuck_job, "macsuck", waiting=waiting)
            arpnip = _step_from_admin(admin, row.arpnip_job, "arpnip", waiting=waiting)
        steps.extend([discover, macsuck, arpnip])
        for item in detail.get("neighbour_jobs") or []:
            if not isinstance(item, dict):
                continue
            step = _step_from_admin(admin, int(item.get("id") or 0), "neighbour")
            nip = str(item.get("ip") or "")
            step["ip"] = nip
            if nip:
                step["message"] = (nip + (": " + step["message"] if step.get("message") else "")).strip()
            steps.append(step)
        status = _overall(steps)
        message = _summary(steps) or row.message or ""
        was_open = row.finished_at is None
        row.status = status
        row.message = message
        if status in ("done", "error") and row.finished_at is None:
            row.finished_at = utcnow()
            detail["final_steps"] = steps
        row.detail = json.dumps(detail)
        return _device_public(row, steps, status, message), status == "done" and was_open

    def note_scans_finished(self) -> int:
        """Mark each queued scan from its own scan-done file.

        A global scan-finished stamp used to mark every queued scan finished
        when any walk ended, including ones that found nothing.
        """
        done_dir = self._out("scan-done")
        if not os.path.isdir(done_dir):
            return 0
        updated = 0
        with self.sf() as db:
            rows = db.scalars(select(DiscoveryScan).where(DiscoveryScan.status == "queued")).all()
            for row in rows:
                path = os.path.join(done_dir, str(row.id))
                if not os.path.isfile(path):
                    continue
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        lines = fh.read().splitlines()
                except OSError:
                    continue
                stamp = _parse_stamp(lines[0] if lines else "")
                if stamp is None or row.started_at is None:
                    continue
                started = row.started_at
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                if started > stamp:
                    continue
                status = (lines[1] if len(lines) > 1 else "finished").strip()
                if status not in ("finished", "failed"):
                    status = "finished"
                message = (lines[2] if len(lines) > 2 else "").strip()
                row.status = status
                row.finished_at = stamp
                if message:
                    row.message = message
                updated += 1
            if updated:
                db.commit()
        return updated

    def list_scans(self) -> list[dict]:
        self.note_scans_finished()
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
        empty = {"ok": False, "roles": [], "sites": [], "platforms": [], "roleChoices": [], "siteChoices": []}
        if not self.netbox_headers():
            return empty
        try:
            roles = self._netbox_get_all("/api/dcim/device-roles/?limit=200")
            sites = self._netbox_get_all("/api/dcim/sites/?limit=1000")
            platforms = self._netbox_get_all("/api/dcim/platforms/?limit=500")
        except Exception:
            return empty
        choices = []
        for row in roles or []:
            name = (row.get("name") or "").strip()
            if not name:
                continue
            choices.append({"name": name, "slug": (row.get("slug") or "").strip()})
        site_choices = []
        for row in sites or []:
            name = (row.get("name") or "").strip()
            if not name:
                continue
            site_choices.append({"name": name, "slug": (row.get("slug") or "").strip()})
        body = {
            "ok": True,
            "roles": _names(roles),
            "roleChoices": choices,
            "sites": _names(sites),
            "siteChoices": site_choices,
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

    def set_roles(self, ids, role: str) -> dict:
        """Remember the NetBox role on pending candidates. Approval reads it back."""
        chosen = (role or "").strip()
        if not chosen or len(chosen) > 64:
            raise ValueError("role is required")
        updated = []
        missing = []
        with self.sf() as db:
            for raw in ids or []:
                try:
                    cid = int(raw)
                except (TypeError, ValueError):
                    missing.append(str(raw))
                    continue
                row = db.get(DiscoveryCandidate, cid)
                if row is None or row.status != "pending":
                    missing.append(str(cid))
                    continue
                row.role_slug = chosen
                updated.append(str(cid))
            db.commit()
        return {"ok": True, "role": chosen, "updated": updated, "missing": missing}

    def set_sites(self, ids, site: str) -> dict:
        """Remember the NetBox site on pending candidates. Approval reads it back."""
        chosen = (site or "").strip()
        if not chosen or len(chosen) > 100:
            raise ValueError("site is required")
        updated = []
        missing = []
        with self.sf() as db:
            for raw in ids or []:
                try:
                    cid = int(raw)
                except (TypeError, ValueError):
                    missing.append(str(raw))
                    continue
                row = db.get(DiscoveryCandidate, cid)
                if row is None or row.status != "pending":
                    missing.append(str(cid))
                    continue
                row.site_slug = chosen
                updated.append(str(cid))
            db.commit()
        return {"ok": True, "site": chosen, "updated": updated, "missing": missing}


_SNMP_ERRORS = {
    "timeout": "no response (timed out)",
    "empty": "empty response",
    "bad_response": "response was not valid",
    "exporter_unreachable": "SNMPv3 exporter could not be reached",
    "auth_not_loaded": "SNMPv3 auth is not loaded yet",
    "no_response": "no response",
    "error": "no response",
}
_STEP_NAMES = ("snmp", "discover", "macsuck", "arpnip")


def _snmp_error_text(code) -> str:
    return _SNMP_ERRORS.get(str(code or "no_response"), "no response")


def _overall(steps: list[dict]) -> str:
    required = [step for step in steps if step.get("name") in _STEP_NAMES]
    if any(step.get("status") == "error" for step in required):
        return "error"
    if required and all(step.get("status") == "done" for step in required):
        return "done"
    discover = next((step for step in required if step.get("name") == "discover"), None)
    if discover and discover.get("status") == "queued":
        return "queued"
    if any(step.get("status") in ("running", "done") for step in required):
        return "running"
    return "queued"


def _summary(steps: list[dict]) -> str:
    for name in ("discover", "snmp", "macsuck", "arpnip"):
        for step in steps:
            if step.get("name") == name and step.get("status") == "error" and step.get("message"):
                return str(step["message"])
    for step in steps:
        if step.get("status") == "running" and step.get("message"):
            return str(step["message"])
    for step in steps:
        if step.get("name") == "snmp" and step.get("message"):
            return str(step["message"])
    return ""


def _names(rows: list[dict]) -> list[str]:
    found = []
    for row in rows or []:
        name = (row.get("name") or row.get("slug") or "").strip()
        if name and name not in found:
            found.append(name)
    return found


def _ipv4_host(value: str) -> str:
    raw = (value or "").strip()
    if not raw or "/" in raw:
        raise ValueError("Enter an IPv4 address.")
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        raise ValueError("Enter an IPv4 address.")
    if not isinstance(addr, ipaddress.IPv4Address):
        raise ValueError("Enter an IPv4 address.")
    return str(addr)


def _userip(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        addr = ipaddress.ip_address(raw.split("%")[0])
    except ValueError:
        return None
    if not isinstance(addr, ipaddress.IPv4Address):
        return None
    return str(addr)


def _load_detail(text: str) -> dict:
    try:
        data = json.loads(text or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _steps_from_detail(detail: dict, status: str) -> list[dict]:
    snmp = detail.get("snmp") if isinstance(detail.get("snmp"), dict) else {}
    snmp_status = snmp.get("status") or status
    message = str(snmp.get("message") or "")
    follow = "error" if snmp_status == "error" else "queued"
    follow_message = "Not started." if snmp_status == "error" else ""
    return [
        {"name": "snmp", "status": snmp_status, "message": message},
        {"name": "discover", "status": follow, "message": follow_message},
        {"name": "macsuck", "status": follow, "message": follow_message},
        {"name": "arpnip", "status": follow, "message": follow_message},
    ]


def _step_from_admin(admin, job_id: int, name: str, waiting: bool = False) -> dict:
    if not job_id:
        if waiting:
            return {"name": name, "status": "queued", "message": "Waiting for discover to finish."}
        return {"name": name, "status": "queued", "message": "Queued in Netdisco."}
    try:
        view = admin.fetch(int(job_id))
    except Exception:
        return {"name": name, "status": "running", "message": "Waiting for Netdisco."}
    if view is None:
        return {"name": name, "status": "error", "message": "Netdisco job was not found."}
    message = view.get("log") or _step_label(name, view.get("status") or "queued")
    return {"name": name, "status": view.get("status") or "queued", "message": message}


def _step_label(name: str, status: str) -> str:
    labels = {
        ("discover", "queued"): "Queued in Netdisco.",
        ("discover", "running"): "Discovering.",
        ("discover", "done"): "Discover finished.",
        ("discover", "error"): "Discover failed.",
        ("macsuck", "queued"): "Queued in Netdisco.",
        ("macsuck", "running"): "Collecting MAC addresses.",
        ("macsuck", "done"): "MAC suck finished.",
        ("macsuck", "error"): "MAC suck failed.",
        ("arpnip", "queued"): "Queued in Netdisco.",
        ("arpnip", "running"): "Collecting ARP.",
        ("arpnip", "done"): "ARP collection finished.",
        ("arpnip", "error"): "ARP collection failed.",
        ("neighbour", "queued"): "Queued in Netdisco.",
        ("neighbour", "running"): "Discovering neighbour.",
        ("neighbour", "done"): "Neighbour discover finished.",
        ("neighbour", "error"): "Neighbour discover failed.",
    }
    return labels.get((name, status), status)


def _device_public(row: DiscoveryDeviceJob, steps: list[dict], status: str, message: str) -> dict:
    body = {
        "id": str(row.id),
        "ip": row.ip,
        "status": status,
        "message": message or "",
        "neighbours": bool(row.neighbours),
        "startedAt": _iso(row.started_at) or "",
        "steps": steps,
    }
    finished = _iso(row.finished_at)
    if finished:
        body["finishedAt"] = finished
    return body


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


def unapproved_for_ui(row: dict, suffixes: list[str] | None = None) -> dict:
    """Shape GET /api/v1/discovery/unapproved the way the Not in NetBox screen reads it."""
    name = strip_hostname(str(row.get("name") or ""), suffixes)
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


def _parse_stamp(text: str):
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _norm_model(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


_FORTINET_PART = re.compile(r"(?i)^fgt[_-]?(.+)$")


def catalog_part(value: str) -> str:
    """Orderable part number. A FortiGate reports FGT_60F for the FG-60F."""
    text = re.sub(r"\s+", " ", (value or "").strip())
    if not text or text.lower() == "unknown":
        return ""
    match = _FORTINET_PART.match(text)
    if match:
        rest = match.group(1).strip(" _-").replace("_", "-")
        if rest:
            return ("FG-" + rest)[:64]
    return text[:64]


def part_lookup_names(value: str) -> list[str]:
    """Spellings to try against a NetBox device type's part number."""
    text = (value or "").strip()
    names: list[str] = []
    for item in (catalog_part(text), text, text.replace("_", "-")):
        item = item.strip()[:64]
        if item and item.lower() != "unknown" and item not in names:
            names.append(item)
    return names


def load_device_aliases(path: str) -> dict:
    """Map a normalized Netdisco model string to library search hints."""
    data = load_yaml(path, {})
    raw = data.get("aliases") if isinstance(data, dict) else None
    out = {}
    for key, spec in (raw or {}).items():
        if isinstance(spec, dict):
            out[_norm_model(str(key))] = spec
    return out


def _iso(value) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


class NetBoxWriter:
    """Creates the objects an approved device needs. Methods are small so tests can fake the client.

    approve_device writes a Netdisco candidate. approve_access_point writes one
    wireless access point from controller telemetry. Both go through this class.
    """

    def __init__(self, base_url: str, headers: dict):
        self.base = base_url.rstrip("/")
        self.headers = dict(headers)
        self.headers["Content-Type"] = "application/json"

    def _req(self, method: str, path: str, body: dict | list | None = None) -> dict:
        with httpx.Client(timeout=20.0) as client:
            resp = client.request(method, self.base + path, headers=self.headers, json=body)
            if resp.status_code >= 400:
                detail = (resp.text or "").strip().replace("\n", " ")[:240]
                raise RuntimeError("netbox %s %s -> %s %s" % (method, path, resp.status_code, detail))
            if resp.content:
                data = resp.json()
                return data if isinstance(data, dict) else {"results": data}
            return {}

    def ensure(self, list_path: str, slug: str, body: dict) -> dict:
        found = self._req("GET", "%s?slug=%s" % (list_path, quote(slug, safe="")))
        results = found.get("results") or []
        if results:
            return results[0]
        # A NetBox slug is not always the slug of the display name. "Core Switch"
        # is stored as core-switches, so a lookup for core-switch misses and a
        # create then fails because that name is already taken.
        name = str(body.get("name") or "").strip()
        if name:
            try:
                by_name = self._req("GET", "%s?name__ie=%s" % (list_path, quote(name, safe="")))
            except RuntimeError:
                by_name = {}
            named = [
                row for row in (by_name.get("results") or [])
                if str(row.get("name") or "").strip().lower() == name.lower()
            ]
            if named:
                return named[0]
        return self._req("POST", list_path, body)

    def _one_type(self, manufacturer_id: int, field: str, value: str) -> dict | None:
        encoded = quote(value, safe="")
        res = self._req(
            "GET",
            "/api/dcim/device-types/?manufacturer_id=%s&%s=%s" % (manufacturer_id, field, encoded),
        ).get("results") or []
        if len(res) == 1:
            return res[0]
        wanted = _norm_model(value)
        same = [row for row in res if _norm_model(row.get("model") or "") == wanted or _norm_model(row.get("part_number") or "") == wanted]
        return same[0] if len(same) == 1 else None

    def find_device_type(self, manufacturer_id: int, model: str, aliases: dict | None = None) -> dict | None:
        """Reuse a library device type. A stub is only for a model with no library hit."""
        if not model or model.lower() == "unknown":
            return None
        aliases = aliases or {}
        spec = aliases.get(_norm_model(model)) or {}
        prefer = [str(item) for item in (spec.get("prefer") or []) if str(item).strip()]
        contains = [str(item) for item in (spec.get("contains") or []) if str(item).strip()]
        names = []
        for item in prefer + [model]:
            for variant in part_lookup_names(item) or [item]:
                if variant not in names:
                    names.append(variant)
        for name in names:
            for field in ("part_number", "model"):
                found = self._one_type(manufacturer_id, field, name)
                if found is not None:
                    return found
        needles = contains or ([model] if not spec else [])
        for needle in needles:
            encoded = quote(needle, safe="")
            rows = self._req(
                "GET",
                "/api/dcim/device-types/?manufacturer_id=%s&q=%s&limit=50" % (manufacturer_id, encoded),
            ).get("results") or []
            wanted = _norm_model(needle)
            ranked = [
                row for row in rows
                if wanted and (
                    wanted in _norm_model(row.get("model") or "")
                    or wanted in _norm_model(row.get("part_number") or "")
                    or wanted in _norm_model(row.get("slug") or "")
                )
            ]
            for name in prefer:
                target = _norm_model(name)
                for row in ranked:
                    blob = _norm_model(row.get("model") or "") + _norm_model(row.get("part_number") or "")
                    if target and target in blob:
                        return row
            if len(ranked) == 1:
                return ranked[0]
            if ranked and spec:
                ranked.sort(key=lambda row: len(row.get("model") or ""))
                return ranked[0]
        return None

    def approve_device(self, candidate: dict, guess: dict, sync_settings: dict, aliases: dict | None = None, suffixes: list[str] | None = None) -> dict:
        # The UI sends names ("Access switch", "Test Site"); NetBox slugs are lower-case with dashes.
        site_name = (candidate.get("site") or sync_settings.get("default_site_slug") or "discovered").strip()
        site_slug = _slug(site_name)
        role_name = (guess.get("role") or sync_settings.get("default_role_slug") or "access-switch").strip()
        role_slug = _slug(role_name)
        mfr_name, mfr_slug = manufacturer_identity(candidate.get("vendor") or "", guess)
        raw_model = (guess.get("model") or "unknown")[:64]
        if (candidate.get("model") or "").strip():
            raw_model = candidate["model"].strip()[:64]
        model = catalog_part(raw_model) or raw_model
        manufacturer = self.ensure("/api/dcim/manufacturers/", mfr_slug, {"name": mfr_name, "slug": mfr_slug})
        dtype = self.find_device_type(manufacturer["id"], model, aliases)
        if dtype is None:
            model_slug = _slug(model)[:40]
            dtype = self.ensure("/api/dcim/device-types/", model_slug, {
                "manufacturer": manufacturer["id"],
                "model": model,
                "slug": model_slug,
                "part_number": model[:50],
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
        name = strip_hostname(
            candidate.get("name") or ("discovered-%s" % candidate["ip"].replace(".", "-")),
            suffixes,
        ) or ("discovered-%s" % candidate["ip"].replace(".", "-"))
        device_body = {
            "name": name[:64],
            "device_type": dtype["id"],
            "role": role["id"],
            "site": site["id"],
            "status": "active",
        }
        # Optional. Backups use status=active, so a missing tag must not fail approval.
        try:
            self.ensure("/api/extras/tags/", "oxidized", {"name": "oxidized", "slug": "oxidized", "color": "ff9800"})
            device_body["tags"] = [{"slug": "oxidized"}]
        except Exception:
            pass
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

    def _ensure_text_field(self, name: str, label: str) -> None:
        found = self._req("GET", "/api/extras/custom-fields/?name=%s" % quote(name, safe=""))
        rows = found.get("results") or []
        if any((row.get("name") or "") == name for row in rows):
            return
        self._req("POST", "/api/extras/custom-fields/", {
            "name": name,
            "label": label,
            "type": "text",
            "object_types": ["dcim.device"],
            "required": False,
        })

    def approve_access_point(self, ap: dict, *, role: str, site: str, platform: str = "") -> dict:
        """Create one Cisco access point. Manufacturer is Cisco. Caller skips APs already in NetBox."""
        role_name = (role or "access-point").strip() or "access-point"
        role_slug = _slug(role_name)
        site_name = (site or "").strip() or "discovered"
        site_slug = _slug(site_name)
        model = catalog_part(str(ap.get("model") or "")) or (str(ap.get("model") or "").strip() or "Access Point")[:64]
        name = (str(ap.get("name") or "").strip() or "access-point")[:64]
        manufacturer = self.ensure("/api/dcim/manufacturers/", "cisco", {"name": "Cisco", "slug": "cisco"})
        dtype = self.find_device_type(manufacturer["id"], model, {})
        if dtype is None:
            model_slug = _slug(model)[:40] or "access-point"
            dtype = self.ensure("/api/dcim/device-types/", model_slug, {
                "manufacturer": manufacturer["id"],
                "model": model,
                "slug": model_slug,
                "part_number": model[:50],
            })
        role_row = self.ensure("/api/dcim/device-roles/", role_slug, {
            "name": role_name, "slug": role_slug, "color": "2196f3",
        })
        site_row = self.ensure("/api/dcim/sites/", site_slug, {
            "name": site_name, "slug": site_slug, "status": "active",
        })
        version = str(ap.get("ios") or ap.get("sw_version") or platform or "").strip()
        platform_id = None
        platform_slug = ""
        platform_name = version or (platform or "").strip()
        if platform_name:
            platform_slug = _slug(platform_name)[:50] or "ios-xe"
            platform_row = self.ensure("/api/dcim/platforms/", platform_slug, {
                "name": platform_name[:64],
                "slug": platform_slug,
                "manufacturer": manufacturer["id"],
            })
            platform_id = platform_row.get("id")
        self._ensure_text_field("ie_sw_version", "Software version")
        self._ensure_text_field("ie_parent_wlc", "Parent WLC")
        custom = {}
        if version:
            custom["ie_sw_version"] = version[:64]
        wlc = str(ap.get("wlc") or "").strip()
        if wlc:
            custom["ie_parent_wlc"] = wlc[:64]
        device_body = {
            "name": name,
            "device_type": dtype["id"],
            "role": role_row["id"],
            "site": site_row["id"],
            "status": "active",
            "custom_fields": custom,
        }
        serial = str(ap.get("serial") or "").strip()
        if serial:
            device_body["serial"] = serial[:50]
        if platform_id:
            device_body["platform"] = platform_id
        if wlc:
            tag_slug = _slug("wlc-%s" % wlc)[:50]
            if tag_slug:
                try:
                    self.ensure("/api/extras/tags/", tag_slug, {
                        "name": ("WLC %s" % wlc)[:50],
                        "slug": tag_slug,
                        "color": "2196f3",
                    })
                    device_body["tags"] = [{"slug": tag_slug}]
                except Exception:
                    pass
        device = self._req("POST", "/api/dcim/devices/", device_body)
        address = _ipv4_address(str(ap.get("ip") or ""))
        if address:
            try:
                iface = self._req("POST", "/api/dcim/interfaces/", {
                    "device": device["id"], "name": "mgmt", "type": "virtual",
                })
                ip = self._req("POST", "/api/ipam/ip-addresses/", {
                    "address": address + "/32",
                    "status": "active",
                    "assigned_object_type": "dcim.interface",
                    "assigned_object_id": iface["id"],
                    "description": "primary address from wireless controller",
                })
                self._req("PATCH", "/api/dcim/devices/%s/" % device["id"], {"primary_ip4": ip["id"]})
            except Exception:
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
