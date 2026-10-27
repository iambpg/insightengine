"""HTTP reload and container restart. Restart names are allow-listed; the proxy is not."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from .db import ReloadState, utcnow
from .errors import ApiError

# Fixed service names that are not client-suffixed, plus the slug suffix checked by the caller.
_FIXED = {"ie-setup", "ie-docker-proxy", "ie-config", "ie-config-docker-proxy"}


def allowed_container(name: str, client_slug: str, registry_names: set[str]) -> bool:
    if not name or "/" in name or ".." in name or len(name) > 128:
        return False
    if name in _FIXED or name in registry_names:
        return True
    if client_slug and client_slug != "unconfigured" and name.endswith("-" + client_slug):
        # still require the name to be one we know, not any suffix match from user input
        return name in registry_names
    return False


class Reloader:
    def __init__(self, settings, session_factory, registry):
        self.settings = settings
        self.sf = session_factory
        self.registry = registry

    def known_names(self) -> set[str]:
        names = set(_FIXED)
        for app in self.registry.apps:
            names.update(n for n in app.containers if n)
        return names

    def http_reload(self, targets: list[dict]) -> dict:
        if not targets:
            return {"ok": True, "message": "nothing to reload", "output": ""}
        lines = []
        ok = True
        try:
            with httpx.Client(timeout=10.0) as client:
                for t in targets:
                    url = t.get("url") or ""
                    method = (t.get("method") or "POST").upper()
                    if method not in ("POST", "PUT"):
                        ok = False
                        lines.append("refusing method %s" % method)
                        continue
                    headers = {}
                    body = None
                    if t.get("body") is not None:
                        body = t["body"]
                        headers["Content-Type"] = t.get("content_type") or "application/json"
                    if t.get("username"):
                        auth = (t["username"], t.get("password") or "")
                    else:
                        auth = None
                    try:
                        resp = client.request(method, url, content=body, headers=headers, auth=auth)
                        lines.append("%s %s -> %s" % (method, url, resp.status_code))
                        if resp.status_code >= 400:
                            ok = False
                            lines.append(resp.text[-500:])
                    except httpx.HTTPError as exc:
                        ok = False
                        lines.append("%s %s failed: %s" % (method, url, exc.__class__.__name__))
        except Exception as exc:  # keep the API up
            return {"ok": False, "message": "reload failed", "output": exc.__class__.__name__}
        return {"ok": ok, "message": "reloaded" if ok else "reload failed", "output": "\n".join(lines)[-4000:]}

    def restart(self, names: list[str]) -> dict:
        known = self.known_names()
        lines = []
        ok = True
        base = self.settings.docker_proxy_url.rstrip("/")
        for name in names:
            if not allowed_container(name, self.settings.client_slug, known):
                ok = False
                lines.append("refusing to restart %r (not in this project's allow-list)" % name)
                continue
            try:
                with httpx.Client(timeout=30.0) as client:
                    # The proxy speaks the Docker API. Restart is POST /containers/{id}/restart.
                    resp = client.post("%s/containers/%s/restart?t=20" % (base, name))
                    lines.append("restart %s -> %s" % (name, resp.status_code))
                    if resp.status_code not in (204, 200):
                        ok = False
                        lines.append(resp.text[-300:])
            except httpx.HTTPError as exc:
                ok = False
                lines.append("restart %s failed: %s" % (name, exc.__class__.__name__))
        return {"ok": ok, "message": "restarted" if ok else "restart failed", "output": "\n".join(lines)[-4000:]}

    def record(self, app: str, ok: bool, message: str) -> None:
        with self.sf() as db:
            row = db.get(ReloadState, app)
            if row is None:
                row = ReloadState(app=app)
                db.add(row)
            row.at = utcnow()
            row.ok = 1 if ok else 0
            row.message = message[:500]
            db.commit()

    def last(self, app: str) -> dict | None:
        with self.sf() as db:
            row = db.get(ReloadState, app)
            if row is None:
                return None
            at = row.at
            if isinstance(at, datetime) and at.tzinfo is None:
                at = at.replace(tzinfo=timezone.utc)
            return {"at": at.strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(at, datetime) else None,
                    "ok": bool(row.ok), "message": row.message}


def container_states(proxy_url: str, names: list[str]) -> dict[str, dict]:
    """Best-effort Docker inspect via the narrow proxy. Missing proxy -> state unknown."""
    out = {n: {"name": n, "state": "unknown"} for n in names if n}
    if not names or not proxy_url:
        return out
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(proxy_url.rstrip("/") + "/containers/json", params={"all": "1"})
            if resp.status_code != 200:
                return out
            wanted = set(names)
            seen = set()
            for item in resp.json():
                raw_names = [n.lstrip("/") for n in (item.get("Names") or [])]
                state = (item.get("State") or "").lower()
                status = item.get("Status") or ""
                health = ""
                if "(unhealthy)" in status:
                    health = "unhealthy"
                elif "(healthy)" in status:
                    health = "healthy"
                mapped = "running" if state == "running" else ("exited" if state else "unknown")
                if health == "unhealthy":
                    mapped = "unhealthy"
                started = item.get("Created") or 0
                for n in raw_names:
                    if n in wanted:
                        seen.add(n)
                        out[n] = {"name": n, "state": mapped, "health": health or None, "status": status, "created": started}
            for n in wanted:
                if n not in seen:
                    out[n] = {"name": n, "state": "missing", "health": None}
    except (httpx.HTTPError, ValueError):
        return out
    return out
