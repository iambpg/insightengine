"""HTTP routes for /api/v1/netbridge."""

from __future__ import annotations

import logging

from fastapi import Request

from ie_config.auth import SETTINGS_ROLES
from ie_config.errors import ApiError

from .service import NetBridge

log = logging.getLogger("ie-config.netbridge")

_KINDS = {"stacks", "addresses", "controllers", "access-points", "sites", "eox"}


def mount_netbridge(app, user_of, audit) -> None:
    def bridge() -> NetBridge:
        service = getattr(app.state, "netbridge", None)
        if service is None:
            service = NetBridge(app.state.settings, app.state.sf, app.state.discovery)
            app.state.netbridge = service
        return service

    def reader(request: Request):
        user, _csrf = user_of(request)
        return user

    def editor(request: Request):
        user = reader(request)
        if getattr(user, "role", "") not in SETTINGS_ROLES:
            raise ApiError(403, "forbidden", "NetBridge writes are limited to Administrators and Engineers")
        return user

    @app.get("/api/v1/netbridge/summary")
    def summary(request: Request):
        reader(request)
        return bridge().summary(refresh=request.query_params.get("refresh") == "1")

    @app.get("/api/v1/netbridge/open-count")
    def open_count(request: Request):
        reader(request)
        return {"open": bridge().open_count()}

    @app.post("/api/v1/netbridge/refresh")
    def refresh(request: Request):
        user = editor(request)
        body = bridge().summary(refresh=True)
        audit(app.state.sf, user, "netbridge-refresh", _ip(request), "ok", "netbridge", "", "", "")
        return body

    @app.get("/api/v1/netbridge/stacks")
    def stacks(request: Request):
        reader(request)
        return bridge().stacks(_q(request, "page"), _q(request, "page_size"), _q(request, "q"))

    @app.get("/api/v1/netbridge/addresses")
    def addresses(request: Request):
        reader(request)
        return bridge().addresses(_q(request, "page"), _q(request, "page_size"), _q(request, "q"))

    @app.get("/api/v1/netbridge/controllers")
    def controllers(request: Request):
        reader(request)
        return bridge().controllers(_q(request, "page"), _q(request, "page_size"), _q(request, "q"))

    @app.get("/api/v1/netbridge/access-points")
    def access_points(request: Request):
        reader(request)
        return bridge().access_points(_q(request, "page"), _q(request, "page_size"), _q(request, "q"), _q(request, "model"))

    @app.post("/api/v1/netbridge/access-points/scan")
    async def scan(request: Request):
        user = editor(request)
        body = await _body(request)
        result = bridge().scan_aps(bridge().actor(user), str(body.get("wlc") or ""))
        audit(app.state.sf, user, "netbridge-ap-scan", _ip(request), "ok" if result.get("ok") else "failed", "netbridge", "", "", "")
        return result

    @app.get("/api/v1/netbridge/fortimanager")
    def fortimanager(request: Request):
        reader(request)
        return bridge().fortimanager(_q(request, "page"), _q(request, "page_size"), _q(request, "q"))

    @app.get("/api/v1/netbridge/sites")
    def sites(request: Request):
        reader(request)
        return bridge().sites(_q(request, "page"), _q(request, "page_size"), _q(request, "q"))

    @app.get("/api/v1/netbridge/conflicts")
    def conflicts(request: Request):
        reader(request)
        return bridge().conflicts(_q(request, "page"), _q(request, "page_size"), _q(request, "q"), _q(request, "status"))

    @app.post("/api/v1/netbridge/conflicts/{cid}")
    async def conflict_action(cid: int, request: Request):
        user = editor(request)
        body = await _body(request)
        try:
            updated = bridge().set_conflict(cid, str(body.get("action") or ""), bridge().actor(user))
        except ValueError as exc:
            raise ApiError(400, "bad_body", str(exc))
        if not updated:
            raise ApiError(404, "not_found", "unknown conflict")
        audit(app.state.sf, user, "netbridge-conflict", _ip(request), "ok", "netbridge", "", "", str(cid))
        return updated

    @app.get("/api/v1/netbridge/history")
    def history(request: Request):
        reader(request)
        return bridge().history(_q(request, "page"), _q(request, "page_size"), _q(request, "q"))

    @app.get("/api/v1/netbridge/eox")
    def eox(request: Request):
        reader(request)
        return bridge().eox_page(_q(request, "page"), _q(request, "page_size"), _q(request, "q"), _q(request, "bucket"))

    @app.post("/api/v1/netbridge/eox/refresh")
    def eox_refresh(request: Request):
        user = editor(request)
        result = bridge().refresh_eox(bridge().actor(user))
        audit(app.state.sf, user, "netbridge-eox", _ip(request), "ok" if result.get("ok") else "failed", "netbridge", "", "", "")
        return result

    @app.post("/api/v1/netbridge/{kind}/preview")
    async def preview(kind: str, request: Request):
        user = editor(request)
        if kind not in _KINDS:
            raise ApiError(404, "not_found", "unknown NetBridge action")
        body = await _body(request)
        try:
            result = bridge().preview(kind, bridge().actor(user), body)
        except ValueError as exc:
            raise ApiError(400, "bad_body", str(exc))
        except Exception as exc:
            log.warning("netbridge preview %s: %s", kind, exc.__class__.__name__)
            raise ApiError(502, "upstream_unavailable", "The preview could not be built")
        audit(app.state.sf, user, "netbridge-preview", _ip(request), "ok", "netbridge", kind, "", "")
        return result

    @app.post("/api/v1/netbridge/{kind}/apply")
    async def apply(kind: str, request: Request):
        user = editor(request)
        if kind not in _KINDS:
            raise ApiError(404, "not_found", "unknown NetBridge action")
        body = await _body(request)
        try:
            result = bridge().apply(kind, bridge().actor(user), body)
        except ValueError as exc:
            raise ApiError(400, "bad_body", str(exc))
        except LookupError:
            raise ApiError(404, "not_found", "unknown preview")
        except RuntimeError as exc:
            if str(exc) == "netbox_token":
                raise ApiError(503, "netbox_token", "NetBox API token is not configured")
            log.warning("netbridge apply %s: %s", kind, exc.__class__.__name__)
            raise ApiError(502, "netbox_error", "NetBox did not accept the change")
        except Exception as exc:
            log.warning("netbridge apply %s: %s", kind, exc.__class__.__name__)
            raise ApiError(502, "netbox_error", "NetBox did not accept the change")
        audit(app.state.sf, user, "netbridge-apply", _ip(request), "ok" if result.get("ok") else "failed", "netbridge", kind, "", "")
        return result


def _q(request: Request, name: str) -> str:
    return request.query_params.get(name) or ""


async def _body(request: Request) -> dict:
    if request.headers.get("content-length") in (None, "0"):
        return {}
    try:
        body = await request.json()
    except Exception:
        raise ApiError(400, "bad_body", "body must be JSON")
    if not isinstance(body, dict):
        raise ApiError(400, "bad_body", "body must be a JSON object")
    return body


def _ip(request: Request) -> str:
    from ie_config.auth import client_ip
    return client_ip(request)
