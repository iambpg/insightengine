"""NetBridge jobs. Reads are live. Writes require a stored preview and confirm."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select

from ie_config.db import NetbridgeAp, NetbridgeConflict, NetbridgeEox, NetbridgeJob, NetbridgePreview, utcnow
from ie_config.vault import secret_value

from . import eox as eox_mod
from . import sources
from .plan import (
    cisco_device,
    detect_conflicts,
    eox_bucket,
    eox_pid,
    geocode_query,
    is_wlc,
    paginate,
    plan_addresses,
    plan_aps,
    plan_controllers,
    plan_eox_writes,
    plan_fortigates,
    plan_sites,
    plan_stacks,
    validate_changes,
)
from .snmp import scan_wlc

log = logging.getLogger("ie-config.netbridge")

PREVIEW_HOURS = 24
_SEARCH = {
    "stacks": ("name", "ip"),
    "addresses": ("device", "address", "interface", "netbox", "action"),
    "controllers": ("name", "ip", "model", "source"),
    "fortimanager": ("name", "serial", "ip", "platform", "adom", "netbox"),
    "sites": ("name", "region", "country", "action"),
    "access-points": ("name", "model", "serial", "ip", "wlc", "neighbor"),
}


def _json(value) -> str:
    return json.dumps(value, default=str)


class NetBridge:
    def __init__(self, settings, sf, discovery=None):
        self.settings = settings
        self.sf = sf
        self.discovery = discovery
        self._cache_at = 0.0
        self._cache = None

    def suffixes(self):
        if self.discovery is not None and hasattr(self.discovery, "hostname_suffixes"):
            return self.discovery.hostname_suffixes()
        return sources.suffixes_for(self.settings)

    def netdisco(self) -> dict:
        return sources.load_netdisco(self.settings.netdisco_database_url)

    def netbox_devices(self) -> list[dict]:
        return sources.load_netbox_devices(self.settings)

    def actor(self, user) -> str:
        return (getattr(user, "email", "") or "")[:320]

    def record(self, kind: str, actor: str, status: str, counts: dict | None = None, errors: list | None = None, detail: str = "") -> int:
        with self.sf() as db:
            row = NetbridgeJob(
                kind=kind[:64],
                actor=actor,
                status=status[:16],
                counts=_json(counts or {}),
                errors=_json(list(errors or [])[:50]),
                detail=(detail or "")[:2000],
                finished_at=utcnow(),
            )
            db.add(row)
            db.commit()
            return row.id

    def summary(self, refresh: bool = False) -> dict:
        now = datetime.now(timezone.utc).timestamp()
        if not refresh and self._cache and now - self._cache_at < 30:
            return dict(self._cache)
        nd = self.netdisco()
        nb = self.netbox_devices()
        suffixes = self.suffixes()
        conflicts = []
        if nd.get("ok"):
            conflicts = detect_conflicts(nd["devices"], nb, suffixes)
            self.persist_conflicts(conflicts)
        stacks = plan_stacks(nd.get("devices") or [], nd.get("modules") or [], nb, suffixes)
        pending_stacks = sum(1 for row in stacks["stacks"] if row.get("pending"))
        ap_pending = self._ap_pending(nb, suffixes)
        missing = 0
        if self.discovery is not None:
            try:
                missing = len(self.discovery.list_unapproved())
            except Exception:
                missing = 0
        body = {
            "netdiscoDevices": len(nd.get("devices") or []) if nd.get("ok") else None,
            "netboxDevices": len(nb),
            "notInNetbox": missing,
            "stacksPending": pending_stacks,
            "apsPending": ap_pending,
            "openConflicts": self.open_count(),
            "netdisco": {"ok": bool(nd.get("ok")), "message": nd.get("message") or ""},
            "eox": self._eox_status(),
            "fortimanager": self._fmg_status(),
            "jobs": self._recent_jobs(8),
        }
        self._cache = body
        self._cache_at = now
        return body

    def open_count(self) -> int:
        with self.sf() as db:
            return int(db.scalar(
                select(func.count()).select_from(NetbridgeConflict).where(NetbridgeConflict.status == "open")
            ) or 0)

    def _ap_pending(self, netbox: list[dict], suffixes) -> int:
        with self.sf() as db:
            rows = db.scalars(select(NetbridgeAp)).all()
            aps = [_ap_public(row) for row in rows]
        if not aps:
            return 0
        planned = plan_aps(aps, netbox, suffixes)
        return sum(1 for row in planned["rows"] if row.get("action") == "create")

    def _recent_jobs(self, limit: int) -> list[dict]:
        with self.sf() as db:
            rows = db.scalars(select(NetbridgeJob).order_by(NetbridgeJob.id.desc()).limit(limit)).all()
            return [_job_public(row) for row in rows]

    def _eox_status(self) -> dict:
        client = self.eox_client()
        if not client.configured:
            return {"configured": False, "message": eox_mod.MISSING}
        return {"configured": True, "message": ""}

    def _fmg_status(self) -> dict:
        url = secret_value(self.settings, "FORTIMANAGER_URL")
        token = secret_value(self.settings, "FORTIMANAGER_TOKEN")
        if not url or not token:
            return {
                "configured": False,
                "message": "FortiManager URL and token are not configured. Add them in Settings → Vault.",
            }
        return {"configured": True, "message": ""}

    def eox_client(self) -> eox_mod.EoxClient:
        return eox_mod.EoxClient(
            secret_value(self.settings, "CISCO_API_CLIENT_ID"),
            secret_value(self.settings, "CISCO_API_CLIENT_SECRET"),
            pause=0.25,
        )

    def persist_conflicts(self, found: list[dict]) -> int:
        added = 0
        with self.sf() as db:
            existing = {
                row.fingerprint: row
                for row in db.scalars(select(NetbridgeConflict)).all()
            }
            for item in found:
                row = existing.get(item["fingerprint"])
                if row is not None and row.status in ("ignored", "resolved"):
                    continue
                detail = _json(item.get("detail") or {})
                if row is None:
                    db.add(NetbridgeConflict(
                        fingerprint=item["fingerprint"],
                        kind=item["kind"],
                        left_label=(item.get("left") or "")[:200],
                        right_label=(item.get("right") or "")[:200],
                        detail=detail,
                        status="open",
                    ))
                    added += 1
                else:
                    row.left_label = (item.get("left") or "")[:200]
                    row.right_label = (item.get("right") or "")[:200]
                    row.detail = detail
                    row.updated_at = utcnow()
            db.commit()
        return added

    def stacks(self, page, page_size, q: str) -> dict:
        nd = self.netdisco()
        nb = self.netbox_devices()
        planned = plan_stacks(nd.get("devices") or [], nd.get("modules") or [], nb, self.suffixes())
        self.persist_conflicts(planned["conflicts"])
        body = paginate(planned["stacks"], page, page_size, q, ["name", "ip"])
        body["message"] = nd.get("message") or ""
        body["pending"] = sum(1 for row in planned["stacks"] if row.get("pending"))
        return body

    def addresses(self, page, page_size, q: str) -> dict:
        nd = self.netdisco()
        nb = self.netbox_devices()
        existing = sources.load_ip_index(self.settings) if nb or nd.get("addresses") else {}
        planned = plan_addresses(nd.get("addresses") or [], nd.get("devices") or [], nb, existing, self.suffixes())
        self.persist_conflicts(planned["conflicts"])
        body = paginate(planned["rows"], page, page_size, q, list(_SEARCH["addresses"]))
        body["message"] = nd.get("message") or ""
        return body

    def controllers(self, page, page_size, q: str) -> dict:
        nd = self.netdisco()
        nb = self.netbox_devices()
        counts = self._ap_counts()
        planned = plan_controllers(nd.get("devices") or [], nb, sources.wlc_file(self.settings), counts, self.suffixes())
        body = paginate(planned["rows"], page, page_size, q, list(_SEARCH["controllers"]))
        body["message"] = nd.get("message") or ""
        return body

    def _ap_counts(self) -> dict:
        counts: dict[str, int] = {}
        with self.sf() as db:
            rows = db.execute(select(NetbridgeAp.wlc, func.count()).group_by(NetbridgeAp.wlc)).all()
        for wlc, total in rows:
            counts[wlc or ""] = int(total or 0)
        return counts

    def access_points(self, page, page_size, q: str, model: str) -> dict:
        needle = (q or "").strip().lower()
        model_name = (model or "").strip()
        with self.sf() as db:
            stmt = select(NetbridgeAp)
            if model_name:
                stmt = stmt.where(NetbridgeAp.model == model_name)
            if needle:
                like = "%" + needle.replace("%", "") + "%"
                stmt = stmt.where(or_(
                    NetbridgeAp.name.ilike(like),
                    NetbridgeAp.serial.ilike(like),
                    NetbridgeAp.ip.ilike(like),
                    NetbridgeAp.wlc.ilike(like),
                    NetbridgeAp.neighbor.ilike(like),
                    NetbridgeAp.model.ilike(like),
                ))
            total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
            try:
                page_i = max(1, int(page or 1))
            except (TypeError, ValueError):
                page_i = 1
            try:
                size = min(100, max(1, int(page_size or 25)))
            except (TypeError, ValueError):
                size = 25
            rows = db.scalars(
                stmt.order_by(NetbridgeAp.wlc, NetbridgeAp.name).offset((page_i - 1) * size).limit(size)
            ).all()
            models = db.execute(
                select(NetbridgeAp.model, func.count()).group_by(NetbridgeAp.model).order_by(func.count().desc())
            ).all()
        return {
            "rows": [_ap_public(row) for row in rows],
            "total": total,
            "page": page_i,
            "pageSize": size,
            "models": [{"model": name or "Unknown", "count": int(count)} for name, count in models],
        }

    def scan_aps(self, actor: str, wlc: str = "") -> dict:
        nd = self.netdisco()
        nb = self.netbox_devices()
        targets = []
        for device in (nd.get("devices") or []):
            if is_wlc(device):
                targets.append(device)
        for device in nb:
            if is_wlc(device):
                targets.append(device)
        targets.extend(sources.wlc_file(self.settings))
        wanted = (wlc or "").strip().lower()
        chosen = []
        seen = set()
        for target in targets:
            ip = (target.get("ip") or "").split("/")[0]
            name = target.get("name") or ip
            if not ip or ip in seen:
                continue
            if wanted and wanted not in (name or "").lower() and wanted != ip:
                continue
            seen.add(ip)
            chosen.append({"ip": ip, "name": name})
        if not chosen:
            self.record("ap-scan", actor, "failed", {"controllers": 0}, ["no wireless controllers to scan"])
            return {"ok": False, "message": "No wireless controllers to scan. Add them in NetBox, Netdisco, or config/discovery/wlc-targets.yml.", "controllers": 0, "aps": 0}
        total = 0
        errors = []
        for target in chosen:
            community = sources.community_for(self.settings, target["ip"])
            result = self.walk_wlc(target["ip"], 161, community)
            if not result.get("ok"):
                errors.append("%s: %s" % (target["name"], result.get("message") or "walk failed"))
                continue
            self._replace_aps(target["name"], result.get("platform") or "", result.get("aps") or [])
            total += len(result.get("aps") or [])
            if result.get("capped"):
                errors.append("%s: walk stopped at the row cap" % target["name"])
        status = "done" if total or not errors else "failed"
        self.record("ap-scan", actor, status, {"controllers": len(chosen), "aps": total}, errors)
        return {"ok": bool(total) or not errors, "message": errors[0] if errors and not total else "Scanned %d access points on %d controllers." % (total, len(chosen)), "controllers": len(chosen), "aps": total, "errors": errors}

    def walk_wlc(self, host: str, port: int, community: str) -> dict:
        return scan_wlc(host, port, community)

    def _replace_aps(self, wlc: str, platform: str, aps: list[dict]) -> None:
        with self.sf() as db:
            for row in db.scalars(select(NetbridgeAp).where(NetbridgeAp.wlc == wlc)).all():
                db.delete(row)
            for ap in aps:
                db.add(NetbridgeAp(
                    wlc=wlc[:128],
                    name=(ap.get("name") or "")[:128],
                    model=(ap.get("model") or "")[:128],
                    serial=(ap.get("serial") or "")[:128],
                    ip=(ap.get("ip") or "")[:64],
                    neighbor=(ap.get("neighbor") or "")[:200],
                    neighbor_port=(ap.get("neighbor_port") or "")[:128],
                    platform=(ap.get("platform") or platform or "")[:32],
                ))
            db.commit()

    def fortimanager(self, page, page_size, q: str) -> dict:
        url = secret_value(self.settings, "FORTIMANAGER_URL")
        token = secret_value(self.settings, "FORTIMANAGER_TOKEN")
        listed = self.fmg_list(url, token)
        if not listed.get("ok"):
            return {
                "rows": [], "total": 0, "page": 1, "pageSize": int(page_size or 25),
                "configured": bool(listed.get("configured")),
                "message": listed.get("message") or "",
                "instances": listed.get("instances") or [],
            }
        compared = plan_fortigates(listed.get("devices") or [], self.netbox_devices(), self.suffixes())
        body = paginate(compared, page, page_size, q, list(_SEARCH["fortimanager"]))
        body["configured"] = True
        body["message"] = ""
        body["instances"] = listed.get("instances") or []
        return body

    def fmg_list(self, url: str, token: str) -> dict:
        return sources.fmg_list(url, token)

    def sites(self, page, page_size, q: str) -> dict:
        sites = [site for site in self.netbox_sites() if site.get("latitude") in (None, "") or site.get("longitude") in (None, "")]
        body = paginate([{
            "id": site.get("id"),
            "name": site.get("name") or "",
            "region": site.get("region") or "",
            "country": site.get("country") or "",
            "action": "missing",
        } for site in sites], page, page_size, q, ["name", "region", "country", "action"])
        body["message"] = "Preview asks Nominatim. Apply writes latitude and longitude only."
        return body

    def netbox_sites(self) -> list[dict]:
        return sources.load_netbox_sites(self.settings)

    def conflicts(self, page, page_size, q: str, status: str) -> dict:
        needle = (q or "").strip().lower()
        wanted = (status or "open").strip().lower()
        if wanted not in ("open", "resolved", "ignored", "all"):
            wanted = "open"
        with self.sf() as db:
            stmt = select(NetbridgeConflict)
            if wanted != "all":
                stmt = stmt.where(NetbridgeConflict.status == wanted)
            if needle:
                like = "%" + needle.replace("%", "") + "%"
                stmt = stmt.where(or_(
                    NetbridgeConflict.kind.ilike(like),
                    NetbridgeConflict.left_label.ilike(like),
                    NetbridgeConflict.right_label.ilike(like),
                ))
            total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
            page_i, size = _page(page, page_size)
            rows = db.scalars(stmt.order_by(NetbridgeConflict.id.desc()).offset((page_i - 1) * size).limit(size)).all()
        return {"rows": [_conflict_public(row) for row in rows], "total": total, "page": page_i, "pageSize": size}

    def set_conflict(self, cid: int, action: str, actor: str) -> dict:
        if action not in ("resolve", "ignore"):
            raise ValueError("action must be resolve or ignore")
        status = "resolved" if action == "resolve" else "ignored"
        with self.sf() as db:
            row = db.get(NetbridgeConflict, cid)
            if row is None:
                return {}
            row.status = status
            row.updated_at = utcnow()
            db.commit()
            public = _conflict_public(row)
        self.record("conflict-" + action, actor, "done", {"id": cid}, [], row.kind)
        return public

    def history(self, page, page_size, q: str) -> dict:
        needle = (q or "").strip().lower()
        with self.sf() as db:
            stmt = select(NetbridgeJob)
            if needle:
                like = "%" + needle.replace("%", "") + "%"
                stmt = stmt.where(or_(NetbridgeJob.kind.ilike(like), NetbridgeJob.actor.ilike(like), NetbridgeJob.status.ilike(like)))
            total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
            page_i, size = _page(page, page_size)
            rows = db.scalars(stmt.order_by(NetbridgeJob.id.desc()).offset((page_i - 1) * size).limit(size)).all()
        return {"rows": [_job_public(row) for row in rows], "total": total, "page": page_i, "pageSize": size}

    def preview(self, kind: str, actor: str, body: dict) -> dict:
        changes, rows, message = self._plan(kind, body or {})
        validate_changes(changes)
        with self.sf() as db:
            row = NetbridgePreview(kind=kind[:64], actor=actor, payload=_json({"changes": changes, "rows": rows[:200]}))
            db.add(row)
            db.commit()
            preview_id = row.id
        self.record(kind + "-preview", actor, "dry-run", {"changes": len(changes)}, [], message)
        return {
            "previewId": preview_id,
            "dryRun": True,
            "kind": kind,
            "changes": len(changes),
            "rows": rows[:200],
            "message": message or "Nothing is written until you confirm this preview.",
        }

    def apply(self, kind: str, actor: str, body: dict) -> dict:
        if not isinstance(body, dict) or body.get("confirm") is not True:
            raise ValueError("confirm must be true")
        try:
            preview_id = int(body.get("previewId") or body.get("preview_id"))
        except (TypeError, ValueError):
            raise ValueError("previewId is required")
        with self.sf() as db:
            row = db.get(NetbridgePreview, preview_id)
            if row is None or row.kind != kind:
                raise LookupError("unknown preview")
            if row.applied:
                raise ValueError("this preview was already applied")
            created = row.created_at
            if created is not None and created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created and created < datetime.now(timezone.utc) - timedelta(hours=PREVIEW_HOURS):
                raise ValueError("this preview has expired")
            try:
                payload = json.loads(row.payload or "{}")
            except ValueError:
                payload = {}
            changes = payload.get("changes") or []
        validate_changes(changes)
        if not changes:
            result = {"counts": {"created": 0, "updated": 0, "skipped": 0, "errors": 0}, "errors": []}
        else:
            result = sources.apply_changes(self.settings, changes)
        with self.sf() as db:
            row = db.get(NetbridgePreview, preview_id)
            if row is not None:
                row.applied = 1
                db.commit()
        self.record(kind + "-apply", actor, "done" if not result["errors"] else "failed", result["counts"], result["errors"])
        self._cache = None
        return {"ok": not result["errors"], "previewId": preview_id, "counts": result["counts"], "errors": result["errors"]}

    def _plan(self, kind: str, body: dict) -> tuple[list, list, str]:
        nd = self.netdisco()
        nb = self.netbox_devices()
        suffixes = self.suffixes()
        if kind == "stacks":
            planned = plan_stacks(nd.get("devices") or [], nd.get("modules") or [], nb, suffixes)
            return _selected_changes(planned["changes"], body, "vc_name", "name"), planned["stacks"], nd.get("message") or ""
        if kind == "addresses":
            existing = sources.load_ip_index(self.settings)
            planned = plan_addresses(nd.get("addresses") or [], nd.get("devices") or [], nb, existing, suffixes)
            wanted = set(str(item) for item in (body.get("ids") or []))
            changes = planned["changes"]
            rows = planned["rows"]
            if wanted:
                rows = [row for row in rows if str(row.get("id")) in wanted]
                addresses = {row["address"] for row in rows}
                changes = [change for change in changes if (change.get("address") or "").split("/")[0] in addresses or change.get("op") == "ensure_interface" and any(
                    (row.get("interface") == change.get("name") and str(row.get("id")).endswith(change.get("name") or "\x00")) for row in rows
                )]
                # Keep interface ensures that match a selected address row's device.
                device_ids = set()
                for change in planned["changes"]:
                    if change.get("op") == "assign_ip" and (change.get("address") or "").split("/")[0] in addresses:
                        device_ids.add(change.get("device_id"))
                changes = [
                    change for change in planned["changes"]
                    if (change.get("op") == "assign_ip" and (change.get("address") or "").split("/")[0] in addresses)
                    or (change.get("op") == "set_primary_if_empty" and (change.get("address") or "").split("/")[0] in addresses)
                    or (change.get("op") == "ensure_interface" and change.get("device_id") in device_ids)
                ]
            return changes, rows, ""
        if kind == "controllers":
            planned = plan_controllers(nd.get("devices") or [], nb, sources.wlc_file(self.settings), self._ap_counts(), suffixes)
            rows = [row for row in planned["rows"] if row.get("action") == "create"]
            changes = list(planned["changes"])
            ids = {str(item) for item in (body.get("ids") or [])}
            if ids:
                rows = [row for row in rows if str(row.get("id")) in ids]
                names = {row.get("name") for row in rows}
                ips = {row.get("ip") for row in rows}
                changes = [change for change in changes if change.get("name") in names or change.get("ip") in ips]
            return changes, rows, ""
        if kind == "access-points":
            ids = {int(item) for item in (body.get("ids") or []) if str(item).isdigit()}
            with self.sf() as db:
                stmt = select(NetbridgeAp)
                if ids:
                    stmt = stmt.where(NetbridgeAp.id.in_(ids))
                aps = [_ap_public(row) for row in db.scalars(stmt).all()]
            planned = plan_aps(aps, nb, suffixes)
            changes = [change for change in planned["changes"] if change.get("op") == "create_device"]
            return changes, [row for row in planned["rows"] if row.get("action") == "create"], ""
        if kind == "sites":
            sites = self.netbox_sites()
            hits = {}
            for site in sites:
                if site.get("latitude") not in (None, "") and site.get("longitude") not in (None, ""):
                    continue
                hit = self.geocode(geocode_query(site), site.get("country_code") or "")
                if hit:
                    hits[str(site.get("id"))] = hit
            planned = plan_sites(sites, hits)
            return planned["changes"], planned["rows"], "Nominatim results are rounded to 6 decimal places."
        if kind == "eox":
            rows = self._eox_rows()
            return plan_eox_writes(rows), rows, "Custom fields are created if missing. Other device fields are not changed."
        raise ValueError("unknown preview")

    def geocode(self, query: str, country_code: str) -> dict | None:
        return sources.nominatim(query, country_code)

    def eox_page(self, page, page_size, q: str, bucket: str) -> dict:
        client = self.eox_client()
        if not client.configured:
            return {
                "configured": False,
                "message": eox_mod.MISSING,
                "rows": [],
                "total": 0,
                "page": 1,
                "pageSize": int(page_size or 25),
                "counts": {"past": 0, "soon": 0, "ok": 0, "unknown": 0},
            }
        needle = (q or "").strip().lower()
        wanted = (bucket or "").strip().lower()
        with self.sf() as db:
            stmt = select(NetbridgeEox)
            if wanted in ("past", "soon", "ok", "unknown"):
                stmt = stmt.where(NetbridgeEox.bucket == wanted)
            if needle:
                like = "%" + needle.replace("%", "") + "%"
                stmt = stmt.where(or_(NetbridgeEox.name.ilike(like), NetbridgeEox.pid.ilike(like), NetbridgeEox.serial.ilike(like)))
            total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
            page_i, size = _page(page, page_size)
            rows = db.scalars(stmt.order_by(NetbridgeEox.name).offset((page_i - 1) * size).limit(size)).all()
            counts = {name: int(total_n or 0) for name, total_n in db.execute(
                select(NetbridgeEox.bucket, func.count()).group_by(NetbridgeEox.bucket)
            ).all()}
        return {
            "configured": True,
            "message": "",
            "rows": [_eox_public(row) for row in rows],
            "total": total,
            "page": page_i,
            "pageSize": size,
            "counts": {
                "past": counts.get("past", 0),
                "soon": counts.get("soon", 0),
                "ok": counts.get("ok", 0),
                "unknown": counts.get("unknown", 0),
            },
        }

    def refresh_eox(self, actor: str) -> dict:
        client = self.eox_client()
        if not client.configured:
            return {"ok": False, "configured": False, "message": eox_mod.MISSING, "updated": 0}
        devices = self._cisco_devices()
        pids = []
        serials = []
        for device in devices:
            pid = eox_pid(device)
            if pid:
                pids.append(pid)
            if device.get("serial"):
                serials.append(device["serial"])
        by_pid = client.lookup_products(pids) if pids else {}
        need_serial = []
        for device in devices:
            pid = eox_pid(device)
            fields = by_pid.get(pid) or {}
            if device.get("serial") and not fields.get("last_date_of_support"):
                need_serial.append(device["serial"])
        by_serial = client.lookup_serials(need_serial) if need_serial else {}
        updated = 0
        with self.sf() as db:
            for device in devices:
                pid = eox_pid(device)
                fields = dict(by_pid.get(pid) or {})
                serial_fields = by_serial.get(device.get("serial") or "") or {}
                if not fields.get("last_date_of_support") and serial_fields:
                    fields = dict(serial_fields)
                    if pid and not fields.get("pid"):
                        fields["pid"] = pid
                key = "nb:%s" % device["id"] if device.get("id") else "nd:%s" % (device.get("ip") or device.get("name"))
                bucket = fields.get("bucket") or eox_bucket(fields.get("last_date_of_support") or "")
                row = db.scalar(select(NetbridgeEox).where(NetbridgeEox.device_key == key))
                values = dict(
                    name=(device.get("name") or "")[:128],
                    pid=(fields.get("pid") or pid or "")[:128],
                    serial=(device.get("serial") or "")[:128],
                    source=device.get("source") or "",
                    netbox_id=str(device.get("id") or "") if device.get("source") == "netbox" else "",
                    end_of_sale=fields.get("end_of_sale") or "",
                    end_of_sw_maintenance=fields.get("end_of_sw_maintenance") or "",
                    end_of_security=fields.get("end_of_security") or "",
                    last_date_of_support=fields.get("last_date_of_support") or "",
                    migration_pid=fields.get("migration_pid") or "",
                    bucket=bucket,
                    message=(fields.get("message") or "")[:500],
                    fetched_at=utcnow(),
                )
                if row is None:
                    db.add(NetbridgeEox(device_key=key[:160], **values))
                else:
                    for name, value in values.items():
                        setattr(row, name, value)
                updated += 1
            db.commit()
        self.record("eox-refresh", actor, "done", {"devices": updated}, [])
        return {"ok": True, "configured": True, "message": "Refreshed %d Cisco devices." % updated, "updated": updated}

    def _cisco_devices(self) -> list[dict]:
        found = []
        seen = set()
        for device in self.netbox_devices():
            if not cisco_device(device):
                continue
            device = dict(device)
            device["source"] = "netbox"
            serial = (device.get("serial") or "").upper()
            if serial and serial in seen:
                continue
            if serial:
                seen.add(serial)
            found.append(device)
        nd = self.netdisco()
        for device in nd.get("devices") or []:
            if not cisco_device(device):
                continue
            serial = (device.get("serial") or "").upper()
            if serial and serial in seen:
                continue
            if serial:
                seen.add(serial)
            item = dict(device)
            item["source"] = "netdisco"
            item["part"] = device.get("model") or ""
            found.append(item)
        return found

    def _eox_rows(self) -> list[dict]:
        with self.sf() as db:
            rows = db.scalars(select(NetbridgeEox).order_by(NetbridgeEox.name)).all()
            return [_eox_public(row) for row in rows]

    def maybe_daily(self) -> None:
        """Scheduler hook. EoX once a day. Conflict comparison every 15 minutes."""
        try:
            self._maybe_conflicts()
        except Exception:
            log.warning("netbridge conflict pass failed")
        try:
            self._maybe_eox()
        except Exception:
            log.warning("netbridge eox pass failed")

    def _maybe_conflicts(self) -> None:
        if not self._due("conflict-scan", minutes=15):
            return
        nd = self.netdisco()
        if not nd.get("ok"):
            return
        found = detect_conflicts(nd.get("devices") or [], self.netbox_devices(), self.suffixes())
        added = self.persist_conflicts(found)
        self.record("conflict-scan", "scheduler", "done", {"open": self.open_count(), "added": added}, [])
        self._cache = None

    def _maybe_eox(self) -> None:
        if not self.eox_client().configured:
            return
        if not self._due("eox-refresh", minutes=24 * 60):
            return
        self.refresh_eox("scheduler")

    def _due(self, kind: str, minutes: int) -> bool:
        with self.sf() as db:
            row = db.scalar(select(NetbridgeJob).where(NetbridgeJob.kind == kind).order_by(NetbridgeJob.id.desc()))
        if row is None or row.started_at is None:
            return True
        started = row.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - started >= timedelta(minutes=minutes)


def _page(page, page_size) -> tuple[int, int]:
    try:
        page_i = max(1, int(page or 1))
    except (TypeError, ValueError):
        page_i = 1
    try:
        size = min(100, max(1, int(page_size or 25)))
    except (TypeError, ValueError):
        size = 25
    return page_i, size


def _selected_changes(changes, body, key, row_key):
    ids = body.get("ids") if isinstance(body, dict) else None
    if not ids:
        return changes
    wanted = {str(item) for item in ids}
    return [change for change in changes if str(change.get(key) or change.get(row_key) or "") in wanted or change.get("op") == "create_vc" and str(change.get("name") or "") in wanted]


def _iso(value) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _job_public(row: NetbridgeJob) -> dict:
    try:
        counts = json.loads(row.counts or "{}")
    except ValueError:
        counts = {}
    try:
        errors = json.loads(row.errors or "[]")
    except ValueError:
        errors = []
    return {
        "id": row.id,
        "kind": row.kind,
        "actor": row.actor,
        "status": row.status,
        "counts": counts,
        "errors": errors,
        "detail": row.detail or "",
        "startedAt": _iso(row.started_at),
        "finishedAt": _iso(row.finished_at),
    }


def _conflict_public(row: NetbridgeConflict) -> dict:
    try:
        detail = json.loads(row.detail or "{}")
    except ValueError:
        detail = {}
    return {
        "id": row.id,
        "kind": row.kind,
        "left": row.left_label,
        "right": row.right_label,
        "status": row.status,
        "detail": detail,
        "updatedAt": _iso(row.updated_at),
    }


def _ap_public(row: NetbridgeAp) -> dict:
    return {
        "id": row.id,
        "wlc": row.wlc,
        "name": row.name,
        "model": row.model,
        "serial": row.serial,
        "ip": row.ip,
        "neighbor": row.neighbor,
        "neighbor_port": row.neighbor_port,
        "platform": row.platform,
        "scannedAt": _iso(row.scanned_at),
    }


def _eox_public(row: NetbridgeEox) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "pid": row.pid,
        "serial": row.serial,
        "source": row.source,
        "netbox_id": row.netbox_id,
        "end_of_sale": row.end_of_sale,
        "end_of_sw_maintenance": row.end_of_sw_maintenance,
        "end_of_security": row.end_of_security,
        "last_date_of_support": row.last_date_of_support,
        "migration_pid": row.migration_pid,
        "bucket": row.bucket,
        "message": row.message,
        "fetchedAt": _iso(row.fetched_at),
    }
