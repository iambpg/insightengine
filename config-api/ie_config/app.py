"""HTTP application for /api/v1 (settings, auth, discovery) and the internal bootstrap."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from .actions import Reloader, container_states
from .auth import SETTINGS_ROLES, Auth, check_bearer, client_ip, read_setup_token, require_csrf, validate_email, validate_password
from .db import AuditRow, make_session_factory
from .discovery import Discovery, NetBoxWriter, guess_device, load_device_aliases, load_yaml, unapproved_for_ui
from .errors import ApiError, error_body
from .fleet import mount_fleet
from .masking import leftover_placeholders, mask_text, restore_secrets
from .registry import AppSpec, FileSpec, Registry, load_registry
from .settings import Settings
from .snmpgen import delete_mib, generate, list_mibs, save_mib
from .storage import atomic_write, backup, etag_of, file_stat, get_history, list_history, read_bytes, unified_diff
from .structured import prometheus_from_jobs, structured_view
from .validators import validate_content

log = logging.getLogger("ie-config")

_CADDY_LOAD = {
    "Caddyfile": "http://caddy:2019/load",
    "Caddyfile.scrape-lb": "http://scrape-lb:2019/load",
}


def _adapt_caddy(path: str) -> tuple[bool, str, str]:
    """Turn a Caddyfile into JSON for the admin /load API. Empty POST bodies are rejected by Caddy."""
    override = os.environ.get("CADDY_BIN")
    binary = override if override else shutil.which("caddy")
    if not binary or not os.path.isfile(binary) or not os.access(binary, os.X_OK):
        return False, "", "caddy is not available in this image; an Administrator can restart Caddy to apply the file"
    try:
        proc = subprocess.run(
            [binary, "adapt", "--config", path, "--adapter", "caddyfile"],
            capture_output=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, "", "caddy adapt failed: %s" % exc.__class__.__name__
    out = (proc.stdout or b"").decode("utf-8", "replace")
    err = (proc.stderr or b"").decode("utf-8", "replace")
    if proc.returncode != 0:
        if "/certs/" in err or "/certs/" in out:
            return False, "", "caddy adapt failed on certificate paths that exist only in the Caddy container; restart Caddy to apply"
        return False, "", (err or out)[-1000:]
    if not out.strip().startswith("{"):
        return False, "", "caddy adapt did not return JSON; restart Caddy to apply"
    return True, out, ""


def _caddy_load_targets(spec: AppSpec, registry: Registry) -> tuple[list[dict], str]:
    targets = []
    for f in spec.files:
        url = _CADDY_LOAD.get(f.id)
        if not url or f.secret_file:
            continue
        try:
            path = registry.resolve(f)
        except ValueError:
            return [], "registry path is not allowed"
        if not os.path.isfile(path):
            return [], "%s does not exist yet" % f.id
        ok, body, err = _adapt_caddy(path)
        if not ok:
            return [], err or "caddy adapt failed"
        targets.append({
            "method": "POST",
            "url": url,
            "body": body.encode("utf-8"),
            "content_type": "application/json",
        })
    if not targets:
        return [], "no Caddyfile to reload"
    return targets, ""


def _audit(sf, user, action, ip, result, app="", file_id="", comment="", detail=""):
    with sf() as db:
        db.add(AuditRow(
            user_email=getattr(user, "email", "") or "",
            role=getattr(user, "role", "") or "",
            action=action,
            app=app or "",
            file_id=file_id or "",
            comment=(comment or "")[:500],
            result=result,
            source_ip=ip or "",
            detail=(detail or "")[:2000],
        ))
        db.commit()


def create_app(settings: Settings | None = None, fleet=None) -> FastAPI:
    settings = settings or Settings.from_env()
    sf, _engine = make_session_factory(settings.database_url)
    registry = load_registry(settings.apps_file, settings.config_root)
    auth = Auth(sf, settings)
    reloader = Reloader(settings, sf, registry)
    discovery = Discovery(settings, sf, settings.config_root)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop = threading.Event()

        def loop():
            # Render once so Netdisco has a deployment.yml even before the first edit.
            try:
                discovery.render_deployment()
            except Exception as exc:
                log.warning("initial netdisco render failed: %s", exc.__class__.__name__)
            # Prefixes are polled about once a minute. The heavy Netdisco walk stays on
            # interval_hours. The queue is refreshed after each pass so a device found
            # by the scheduler shows up on this cycle, not the next one.
            while not stop.is_set():
                cfg = {}
                try:
                    cfg = discovery.read_sync_settings()
                    discovery.sync_prefixes()
                    discovery.refresh_unapproved()
                    discovery.note_scans_finished()
                except Exception as exc:
                    log.warning("discovery loop: %s", exc.__class__.__name__)
                try:
                    poll = int(cfg.get("prefix_poll_seconds") or 60)
                except (TypeError, ValueError):
                    poll = 60
                poll = min(300, max(15, poll))
                if stop.wait(poll):
                    break

        thread = None
        if settings.scheduler:
            thread = threading.Thread(target=loop, name="discovery", daemon=True)
            thread.start()
        yield
        stop.set()

    app = FastAPI(title="ie-config", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.settings = settings
    app.state.sf = sf
    app.state.registry = registry
    app.state.auth = auth
    app.state.discovery = discovery
    app.state.fleet = fleet

    @app.exception_handler(ApiError)
    async def _api_error(_request, exc: ApiError):
        return JSONResponse(status_code=exc.status, content=error_body(exc))

    @app.middleware("http")
    async def _limit(request: Request, call_next):
        raw = request.headers.get("content-length")
        if raw and raw.isdigit() and int(raw) > settings.max_body:
            body = error_body(ApiError(413, "too_large", "request body exceeds 6 MB"))
            return JSONResponse(status_code=413, content=body)
        return await call_next(request)

    def user_of(request: Request):
        user, csrf = auth.session_user(request.cookies.get(settings.cookie_name))
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            require_csrf(request.headers.get("x-csrf-token", ""), csrf)
        return user, csrf

    def require_reader(user):
        if user.role not in SETTINGS_ROLES:
            raise ApiError(403, "forbidden", "Settings is available to Administrators and Engineers")

    def require_editor(user, spec: AppSpec):
        require_reader(user)
        if spec.sensitive and user.role != "Administrator":
            raise ApiError(403, "forbidden", "this application is restricted to Administrators")

    def app_or_404(app_id: str) -> AppSpec:
        spec = registry.get(app_id)
        if spec is None:
            raise ApiError(404, "not_found", "unknown application")
        return spec

    def file_or_404(spec: AppSpec, file_id: str) -> FileSpec:
        # file ids are registry keys, never paths
        if not file_id or "/" in file_id or "\\" in file_id or ".." in file_id:
            raise ApiError(404, "not_found", "unknown file")
        f = spec.file(file_id)
        if f is None:
            raise ApiError(404, "not_found", "unknown file")
        return f

    def load_text(spec: FileSpec) -> tuple[str, str]:
        if spec.secret_file:
            raise ApiError(403, "secret_file", "this file is a secret and is never returned")
        try:
            path = registry.resolve(spec)
        except ValueError:
            raise ApiError(400, "bad_path", "registry path is not allowed")
        data = read_bytes(path)
        if data is None:
            raise ApiError(404, "not_found", "file does not exist yet")
        return data.decode("utf-8", "replace"), etag_of(data)

    def container_brief(spec: AppSpec) -> dict:
        name = spec.container
        states = container_states(settings.docker_proxy_url, [name] if name else [])
        st = states.get(name) or {"name": name, "state": "missing" if not name else "unknown"}
        brief = {"name": name, "state": st.get("state") or "unknown"}
        if st.get("health"):
            brief["health"] = st["health"]
        return brief

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/internal/user-count")
    def user_count(request: Request):
        token = read_setup_token(settings.setup_token_file)
        if not check_bearer(request.headers.get("authorization", ""), token):
            raise ApiError(401, "unauthorized", "missing or invalid token")
        return {"count": auth.user_count()}

    @app.post("/internal/bootstrap-admin")
    async def bootstrap(request: Request):
        token = read_setup_token(settings.setup_token_file)
        if not check_bearer(request.headers.get("authorization", ""), token):
            raise ApiError(401, "unauthorized", "missing or invalid token")
        if auth.user_count():
            raise ApiError(409, "already_bootstrapped", "an administrator already exists")
        body = await request.json()
        email = validate_email(body.get("email", ""))
        password = validate_password(body.get("password", ""))
        # The password is hashed and never logged.
        auth.create_user(email, password, "Administrator")
        _audit(sf, None, "bootstrap-admin", client_ip(request), "ok", detail=email)
        log.info("bootstrapped initial administrator %s", email)
        return {"ok": True}

    @app.post("/api/v1/auth/login")
    async def login(request: Request):
        body = await request.json()
        ip = client_ip(request)
        try:
            result = auth.login(body.get("email", ""), body.get("password", ""), ip)
        except ApiError as exc:
            _audit(sf, None, "login", ip, exc.code, detail=str(body.get("email") or "")[:320])
            raise
        from types import SimpleNamespace
        _audit(sf, SimpleNamespace(email=result["email"], role=result["role"]), "login", ip, "ok")
        resp = JSONResponse({"ok": True, "role": result["role"], "csrfToken": result["csrf"]})
        resp.set_cookie(
            settings.cookie_name, result["token"], httponly=True, secure=settings.cookie_secure,
            samesite="lax", path="/", max_age=settings.session_hours * 3600,
        )
        return resp

    @app.post("/api/v1/auth/logout")
    def logout(request: Request):
        user, _csrf = user_of(request)
        auth.logout(request.cookies.get(settings.cookie_name))
        _audit(sf, user, "logout", client_ip(request), "ok")
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(settings.cookie_name, path="/")
        return resp

    @app.get("/api/v1/auth/me")
    def me(request: Request):
        user, csrf = user_of(request)
        return {"email": user.email, "role": user.role, "csrfToken": csrf}

    @app.get("/api/v1/auth/users")
    def list_users(request: Request):
        user, _csrf = user_of(request)
        if user.role != "Administrator":
            raise ApiError(403, "forbidden", "only an Administrator can list users")
        from .db import User
        with sf() as db:
            rows = db.scalars(select(User).order_by(User.id)).all()
            return [{"email": r.email, "role": r.role} for r in rows]

    @app.post("/api/v1/auth/users")
    async def add_user(request: Request):
        user, _csrf = user_of(request)
        if user.role != "Administrator":
            raise ApiError(403, "forbidden", "only an Administrator can create users")
        body = await request.json()
        created = auth.create_user(body.get("email", ""), body.get("password", ""), body.get("role", ""))
        _audit(sf, user, "create-user", client_ip(request), "ok", detail=created.email + " " + created.role)
        return {"ok": True, "email": created.email, "role": created.role}

    @app.get("/api/v1/settings/apps")
    def list_apps(request: Request):
        user, _csrf = user_of(request)
        require_reader(user)
        names = [a.container for a in registry.apps if a.container]
        states = container_states(settings.docker_proxy_url, names)
        out = []
        for spec in registry.apps:
            st = states.get(spec.container) or {"name": spec.container, "state": "unknown"}
            files = []
            for f in spec.files:
                _path, size, _mtime = file_stat(registry, f)
                editable = f.editable and not f.secret_file and size <= settings.max_edit
                reason = f.read_only_reason
                if f.secret_file:
                    reason = reason or "Secret file; contents are never returned"
                elif size > settings.max_edit:
                    reason = reason or "File is larger than 5 MB and is read-only"
                item = {
                    "id": f.id, "path": f.path, "label": f.label, "language": f.language,
                    "sizeBytes": size, "editable": editable, "hasSecrets": f.has_secrets or f.secret_file,
                }
                if reason and not editable:
                    item["readOnlyReason"] = reason
                files.append(item)
            out.append({
                "id": spec.id, "name": spec.name, "description": spec.description, "group": spec.group,
                "container": {"name": spec.container, "state": st.get("state") or "unknown",
                              **({"health": st["health"]} if st.get("health") else {})},
                "version": spec.version or None,
                "uiUrl": spec.ui_url or None,
                "files": files,
                "actions": [{"id": a.id, "label": a.label, "kind": a.kind, "dangerous": a.dangerous, "roles": a.roles}
                            for a in spec.actions],
            })
        return out

    @app.get("/api/v1/settings/overview")
    def overview(request: Request):
        user, _csrf = user_of(request)
        require_reader(user)
        names = [a.container for a in registry.apps if a.container]
        states = container_states(settings.docker_proxy_url, names)
        apps = []
        for spec in registry.apps:
            st = states.get(spec.container) or {"state": "unknown"}
            last = reloader.last(spec.id)
            failed = bool(last) and not last.get("ok")
            apps.append({
                "id": spec.id,
                "container": {"name": spec.container, "state": st.get("state") or "unknown",
                              **({"health": st["health"]} if st.get("health") else {}),
                              **({"uptimeSeconds": st["uptimeSeconds"]} if st.get("uptimeSeconds") is not None else {})},
                "lastReloadAt": (last or {}).get("at"),
                "lastError": ((last or {}).get("message") or "reload failed") if failed else None,
                "lastReload": last,
            })
        return {"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "apps": apps}

    @app.get("/api/v1/settings/audit")
    def audit(request: Request):
        user, _csrf = user_of(request)
        require_reader(user)
        q = request.query_params
        page = max(1, int(q.get("page") or 1))
        with sf() as db:
            stmt = select(AuditRow).order_by(AuditRow.id.desc())
            if q.get("app"):
                stmt = stmt.where(AuditRow.app == q.get("app"))
            if q.get("user"):
                stmt = stmt.where(AuditRow.user_email == q.get("user"))
            rows = db.scalars(stmt).all()
        # from/to are ISO prefixes; filter in Python to keep the query portable
        def keep(row):
            iso = row.ts.strftime("%Y-%m-%dT%H:%M:%SZ") if row.ts else ""
            if q.get("from") and iso < q.get("from"):
                return False
            if q.get("to") and iso > q.get("to"):
                return False
            return True
        rows = [r for r in rows if keep(r)]
        start = (page - 1) * 50
        page_rows = rows[start:start + 50]
        return {
            "page": page,
            "entries": [{
                "id": r.id,
                "at": r.ts.strftime("%Y-%m-%dT%H:%M:%SZ") if r.ts else None,
                "user": r.user_email, "role": r.role, "action": r.action,
                "app": r.app, "file": r.file_id, "comment": r.comment,
                "result": r.result, "sourceIp": r.source_ip,
            } for r in page_rows],
        }

    @app.get("/api/v1/settings/apps/{app_id}/files/{file_id}")
    def get_file(app_id: str, file_id: str, request: Request):
        user, _csrf = user_of(request)
        require_reader(user)
        spec = app_or_404(app_id)
        f = file_or_404(spec, file_id)
        text, tag = load_text(f)
        masked, keys = mask_text(text)
        path, _size, mtime = file_stat(registry, f)
        return {"content": masked, "etag": tag, "modifiedAt": mtime, "language": f.language, "maskedKeys": keys}

    @app.get("/api/v1/settings/apps/{app_id}/files/{file_id}/structured")
    def get_structured(app_id: str, file_id: str, request: Request):
        user, _csrf = user_of(request)
        require_reader(user)
        spec = app_or_404(app_id)
        f = file_or_404(spec, file_id)
        text, _tag = load_text(f)
        view = structured_view(spec.id, f.id, text)
        if view is None:
            raise ApiError(404, "not_found", "this file has no structured view; use the raw editor")
        return view

    @app.post("/api/v1/settings/apps/{app_id}/files/{file_id}/validate")
    async def validate(app_id: str, file_id: str, request: Request):
        user, _csrf = user_of(request)
        require_reader(user)
        spec = app_or_404(app_id)
        f = file_or_404(spec, file_id)
        body = await request.json()
        content = body.get("content")
        if not isinstance(content, str):
            raise ApiError(400, "bad_body", "content must be a string")
        current = _current_text(f)
        content = restore_secrets(content, current)
        rules = _sibling_rules(spec, f)
        return validate_content(f.validator, f.language, content, rules)

    @app.post("/api/v1/settings/apps/{app_id}/files/{file_id}/diff")
    async def diff(app_id: str, file_id: str, request: Request):
        user, _csrf = user_of(request)
        require_reader(user)
        spec = app_or_404(app_id)
        f = file_or_404(spec, file_id)
        body = await request.json()
        content = body.get("content")
        if not isinstance(content, str):
            raise ApiError(400, "bad_body", "content must be a string")
        current = _current_text(f)
        proposed = restore_secrets(content, current)
        return unified_diff(mask_text(current)[0], mask_text(proposed)[0], f.path)

    @app.put("/api/v1/settings/apps/{app_id}/files/{file_id}")
    async def put_file(app_id: str, file_id: str, request: Request):
        user, _csrf = user_of(request)
        spec = app_or_404(app_id)
        f = file_or_404(spec, file_id)
        require_editor(user, spec)
        if f.secret_file or not f.editable:
            raise ApiError(403, "read_only", f.read_only_reason or "this file is not editable")
        body = await request.json()
        content = body.get("content")
        if not isinstance(content, str):
            raise ApiError(400, "bad_body", "content must be a string")
        if len(content.encode("utf-8")) > settings.max_edit:
            raise ApiError(413, "too_large", "editable files are limited to 5 MB")
        comment = body.get("comment") or ""
        if not isinstance(comment, str) or len(comment) > 500:
            raise ApiError(400, "bad_comment", "comment must be a string of at most 500 characters")
        try:
            path = registry.resolve(f)
        except ValueError:
            raise ApiError(400, "bad_path", "registry path is not allowed")
        current_bytes = read_bytes(path)
        current_tag = etag_of(current_bytes) if current_bytes is not None else ""
        supplied = body.get("etag")
        if supplied is None:
            raise ApiError(400, "etag_required", "etag is required (empty string creates the file)")
        if supplied != current_tag:
            raise ApiError(409, "etag_conflict", "the file changed; reload it and try again", {"etag": current_tag})
        current_text = current_bytes.decode("utf-8", "replace") if current_bytes else ""
        restored = restore_secrets(content, current_text)
        left = leftover_placeholders(restored)
        if left:
            raise ApiError(422, "secret_placeholder", "unknown secret placeholder; replace it or reload the file", {"placeholders": left})
        rules = _sibling_rules(spec, f)
        result = validate_content(f.validator, f.language, restored, rules)
        if not result["ok"]:
            _audit(sf, user, "validate", client_ip(request), "invalid", spec.id, f.id, comment)
            payload = error_body(ApiError(422, "validation_failed", "configuration is invalid", result))
            payload.update(result)
            return JSONResponse(status_code=422, content=payload)
        if current_bytes is not None:
            backup(settings.history_dir, spec.id, f.id, current_bytes, user.email, comment or "before save",
                   settings.history_keep, settings.history_days)
        data = restored.encode("utf-8")
        atomic_write(path, data)
        new_tag = etag_of(data)
        _audit(sf, user, "save", client_ip(request), "ok", spec.id, f.id, comment)
        applied = False
        apply_result = None
        if body.get("apply") is True:
            action = spec.action("reload") or spec.action("restart")
            apply_result = _run_action(spec, action, user, request, restored)
            applied = bool(apply_result and apply_result.get("ok"))
            if spec.id == "netdisco":
                discovery.render_deployment()
                discovery.sync_prefixes()
        return {"etag": new_tag, "applied": applied, "applyResult": apply_result}

    def _current_text(f: FileSpec) -> str:
        try:
            path = registry.resolve(f)
        except ValueError:
            return ""
        data = read_bytes(path)
        return data.decode("utf-8", "replace") if data else ""

    def _sibling_rules(spec: AppSpec, f: FileSpec) -> str | None:
        if spec.id == "prometheus" and f.id == "prometheus.yml":
            rules = spec.file("alert-rules.yml")
            if rules:
                return _current_text(rules)
        return None

    def _run_action(spec: AppSpec, action, user, request, content: str | None = None) -> dict:
        if action is None:
            return {"ok": False, "message": "this application has no reload action"}
        if user.role not in action.roles:
            raise ApiError(403, "forbidden", "your role cannot run this action")
        if action.kind == "reload":
            if spec.id == "caddy":
                targets, err = _caddy_load_targets(spec, registry)
                if err:
                    result = {"ok": False, "message": err, "output": ""}
                else:
                    result = reloader.http_reload(targets)
            else:
                result = reloader.http_reload([dict(t) for t in action.http])
        elif action.kind == "restart":
            result = reloader.restart(action.containers or spec.containers)
        elif action.kind == "validate":
            messages = []
            ok = True
            for f in spec.files:
                if f.secret_file or not f.editable:
                    continue
                text = _current_text(f)
                one = validate_content(f.validator, f.language, text, _sibling_rules(spec, f))
                messages.append("%s: %s" % (f.id, "ok" if one["ok"] else "invalid"))
                ok = ok and one["ok"]
            result = {"ok": ok, "message": "validated", "output": "\n".join(messages)}
        else:
            result = {"ok": False, "message": "unsupported action kind"}
        reloader.record(spec.id, bool(result.get("ok")), result.get("message") or "")
        _audit(sf, user, action.id, client_ip(request), "ok" if result.get("ok") else "failed", spec.id, "", "", result.get("message") or "")
        return result

    @app.get("/api/v1/settings/apps/{app_id}/files/{file_id}/history")
    def history(app_id: str, file_id: str, request: Request):
        user, _csrf = user_of(request)
        require_reader(user)
        spec = app_or_404(app_id)
        file_or_404(spec, file_id)
        return list_history(settings.history_dir, spec.id, file_id)

    @app.get("/api/v1/settings/apps/{app_id}/files/{file_id}/history/{hid}")
    def history_one(app_id: str, file_id: str, hid: str, request: Request):
        user, _csrf = user_of(request)
        require_reader(user)
        spec = app_or_404(app_id)
        f = file_or_404(spec, file_id)
        rec = get_history(settings.history_dir, spec.id, f.id, hid)
        if rec is None:
            raise ApiError(404, "not_found", "unknown history entry")
        masked, keys = mask_text(rec["content"])
        return {"id": rec["id"], "content": masked, "maskedKeys": keys, "savedAt": rec["savedAt"], "user": rec["user"], "comment": rec["comment"]}

    @app.post("/api/v1/settings/apps/{app_id}/files/{file_id}/history/{hid}/restore")
    async def restore(app_id: str, file_id: str, hid: str, request: Request):
        user, _csrf = user_of(request)
        spec = app_or_404(app_id)
        f = file_or_404(spec, file_id)
        require_editor(user, spec)
        if f.secret_file or not f.editable:
            raise ApiError(403, "read_only", "this file is not editable")
        rec = get_history(settings.history_dir, spec.id, f.id, hid)
        if rec is None:
            raise ApiError(404, "not_found", "unknown history entry")
        body = {}
        if request.headers.get("content-length") not in (None, "0"):
            body = await request.json()
        path = registry.resolve(f)
        current = read_bytes(path)
        if current is not None:
            backup(settings.history_dir, spec.id, f.id, current, user.email, "before restore", settings.history_keep, settings.history_days)
        data = rec["content"].encode("utf-8")
        checked = validate_content(f.validator, f.language, rec["content"], _sibling_rules(spec, f))
        if not checked["ok"]:
            payload = error_body(ApiError(422, "validation_failed", "the historical file does not validate", checked))
            payload.update(checked)
            return JSONResponse(status_code=422, content=payload)
        atomic_write(path, data)
        _audit(sf, user, "restore", client_ip(request), "ok", spec.id, f.id, rec.get("comment") or "")
        apply_result = None
        applied = False
        if body.get("apply") is True:
            action = spec.action("reload") or spec.action("restart")
            apply_result = _run_action(spec, action, user, request, rec["content"])
            applied = bool(apply_result and apply_result.get("ok"))
        return {"etag": etag_of(data), "applied": applied, "applyResult": apply_result}

    @app.post("/api/v1/settings/apps/{app_id}/actions/{action_id}")
    async def run_action(app_id: str, action_id: str, request: Request):
        user, _csrf = user_of(request)
        spec = app_or_404(app_id)
        require_reader(user)
        action = spec.action(action_id)
        if action is None:
            raise ApiError(404, "not_found", "unknown action")
        if user.role not in action.roles:
            raise ApiError(403, "forbidden", "your role cannot run this action")
        if action.kind == "generate":
            return _generate(spec)
        if action.id == "scan-now":
            # Sync first so a prefix added a moment ago is in scan-prefixes.txt
            # before the scheduler wakes up.
            synced = discovery.sync_prefixes()
            discovery.request_scan()
            result = {
                "ok": bool(synced.get("ok", True)),
                "message": "prefixes synced; scan requested; the Netdisco scheduler will pick it up within a minute",
                "prefixes": synced.get("prefixes") or [],
            }
            _audit(sf, user, "scan-now", client_ip(request), "ok" if result["ok"] else "failed", spec.id, "", "", synced.get("message") or "")
            return result
        if action.id == "sync-prefixes":
            result = discovery.sync_prefixes()
            _audit(sf, user, "sync-prefixes", client_ip(request), "ok" if result.get("ok") else "failed", spec.id, "", "", result.get("message") or "")
            return result
        if action.id == "refresh-unapproved":
            result = discovery.refresh_unapproved()
            _audit(sf, user, "refresh-unapproved", client_ip(request), "ok" if result.get("ok") else "failed", spec.id)
            return result
        return _run_action(spec, action, user, request, None)

    def _generate(spec: AppSpec):
        gen = spec.file("generator.yml")
        live = registry.get("snmp-exporter")
        live_file = live.file("snmp.yml") if live else None
        if gen is None or live_file is None:
            raise ApiError(500, "misconfigured", "generator or snmp.yml is not in the registry")
        result = generate(
            settings.generator_bin,
            registry.resolve(gen),
            settings.mib_dir,
            registry.resolve(live_file),
            settings.candidate_dir,
        )
        # Do not echo a failed binary path's environment. Content is the candidate, not a secret
        # (auths in the generated file use ${VAR} references).
        return result

    @app.get("/api/v1/settings/apps/snmp-generator/mibs")
    def mib_list(request: Request):
        user, _csrf = user_of(request)
        require_reader(user)
        app_or_404("snmp-generator")
        return list_mibs(settings.mib_dir)

    @app.post("/api/v1/settings/apps/snmp-generator/mibs")
    async def mib_upload(request: Request):
        user, _csrf = user_of(request)
        spec = app_or_404("snmp-generator")
        require_editor(user, spec)
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise ApiError(400, "bad_body", "send a multipart file field named file")
        data = await upload.read()
        try:
            save_mib(settings.mib_dir, os.path.basename(upload.filename or ""), data, settings.mib_file_max, settings.mib_total_max)
        except ValueError as exc:
            raise ApiError(400, "bad_mib", str(exc))
        stored = os.path.basename(upload.filename or "")
        _audit(sf, user, "mib-upload", client_ip(request), "ok", "snmp-generator", "", stored)
        match = next((item for item in list_mibs(settings.mib_dir) if item["name"] == stored), None)
        return match or {"name": stored, "sizeBytes": len(data), "uploadedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    @app.delete("/api/v1/settings/apps/snmp-generator/mibs/{name}")
    def mib_delete(name: str, request: Request):
        user, _csrf = user_of(request)
        spec = app_or_404("snmp-generator")
        require_editor(user, spec)
        if not delete_mib(settings.mib_dir, name):
            raise ApiError(404, "not_found", "unknown MIB")
        _audit(sf, user, "mib-delete", client_ip(request), "ok", "snmp-generator", "", name)
        return {"ok": True}

    @app.get("/api/v1/discovery/catalog")
    def discovery_catalog(request: Request):
        user, _csrf = user_of(request)
        require_reader(user)
        return discovery.catalog()

    @app.get("/api/v1/discovery/unapproved")
    def unapproved(request: Request):
        user, _csrf = user_of(request)
        require_reader(user)
        return [unapproved_for_ui(row) for row in discovery.list_unapproved()]

    @app.post("/api/v1/discovery/{cid}/approve")
    async def approve(cid: int, request: Request):
        user, _csrf = user_of(request)
        require_reader(user)
        body = {}
        if request.headers.get("content-length") not in (None, "0"):
            body = await request.json()
        with sf() as db:
            from .db import DiscoveryCandidate
            row = db.get(DiscoveryCandidate, cid)
            if row is None:
                raise ApiError(404, "not_found", "unknown discovery candidate")
            if row.status != "pending":
                raise ApiError(409, "not_pending", "this candidate is already %s" % row.status)
            candidate = {
                "ip": row.ip,
                "name": body.get("name") or row.name,
                "site": body.get("site") or row.site_slug,
                "sysdescr": row.sysdescr,
                "sysobjectid": row.sysobjectid,
                "vendor": row.vendor,
                "model": row.model,
            }
            stored_guess = {}
            try:
                stored_guess = json.loads(row.detail or "{}")
            except ValueError:
                stored_guess = {}
        mapping = load_yaml(discovery.sysobject_path(), {})
        guess = guess_device(candidate.get("sysobjectid") or "", candidate.get("sysdescr") or "", mapping)
        guess.update({k: v for k, v in stored_guess.items() if v})
        if body.get("role"):
            guess["role"] = body["role"]
        if body.get("platform"):
            guess["platform"] = body["platform"]
        headers = discovery.netbox_headers()
        if not headers:
            raise ApiError(503, "netbox_token", "NetBox API token is not configured")
        try:
            # The only NetBox device create on the discovery path. Reject and the
            # unapproved list never call this.
            created = NetBoxWriter(settings.netbox_url, headers).approve_device(
                candidate, guess, discovery.read_sync_settings(), load_device_aliases(discovery.alias_path()),
            )
        except Exception as exc:
            _audit(sf, user, "discovery-approve", client_ip(request), "failed", "netdisco", "", "", exc.__class__.__name__)
            raise ApiError(502, "netbox_error", "NetBox did not accept the device")
        discovery.set_status(cid, "approved", str(created.get("device_id") or ""), json.dumps(created))
        _audit(sf, user, "discovery-approve", client_ip(request), "ok", "netdisco", "", "", candidate["ip"])
        return {"ok": True, "id": str(cid), "device": created}

    @app.post("/api/v1/discovery/{cid}/reject")
    def reject(cid: int, request: Request):
        user, _csrf = user_of(request)
        require_reader(user)
        updated = discovery.set_status(cid, "rejected")
        if updated is None:
            raise ApiError(404, "not_found", "unknown discovery candidate")
        _audit(sf, user, "discovery-reject", client_ip(request), "ok", "netdisco", "", "", updated["ip"])
        return {"ok": True, "id": str(cid)}

    @app.get("/api/v1/discovery/scans")
    def scans(request: Request):
        user, _csrf = user_of(request)
        require_reader(user)
        return discovery.list_scans()

    @app.post("/api/v1/discovery/scan")
    async def scan(request: Request):
        user, _csrf = user_of(request)
        require_reader(user)
        try:
            body = await request.json()
        except Exception:
            raise ApiError(400, "bad_body", "body must be JSON")
        if not isinstance(body, dict):
            raise ApiError(400, "bad_body", "body must be a JSON object")
        try:
            created = discovery.queue_manual_scan(body.get("target"), body.get("value"))
        except ValueError as exc:
            raise ApiError(400, "invalid_scan", str(exc))
        _audit(sf, user, "discovery-scan", client_ip(request), "ok", "netdisco", "", "", body.get("target") or "")
        return created

    mount_fleet(app, user_of)
    warn_complete_setup_without_users(settings, auth)
    return app


def warn_complete_setup_without_users(settings: Settings, auth: Auth) -> None:
    """Log when data/setup says complete and the users table is empty.

    The setup service owns the state file and reopens the admin step.
    This process only reports the mismatch. A missing file, or a failure
    to read the database, does not change anything.
    """
    path = os.path.join(settings.config_root, "data", "setup", "config.json")
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        return
    if not isinstance(cfg, dict) or cfg.get("state") != "complete":
        return
    try:
        count = auth.user_count()
    except Exception:
        log.error("setup state is complete; could not count ie-config users, so nothing was changed")
        return
    if count == 0:
        log.error(
            "setup state is complete but the ie-config users table is empty. "
            "Create the administrator with sudo ./scripts/reset-admin-password.sh. "
            "The setup service reopens the first-administrator step when it can read this count."
        )
