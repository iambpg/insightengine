"""Approval API for the parent/child tree. Writes happen only here."""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import PlainTextResponse

from .auth import can_operate
from .errors import ApiError
from .fleet import FleetService, UpstreamError, _as_upstream
from .hierarchy import metrics_text, proposal_items, read_auto_apply, write_auto_apply

log = logging.getLogger("ie_config.hierarchy")


def mount_hierarchy(app, user_of) -> None:
    def fleet() -> FleetService:
        service = getattr(app.state, "fleet", None)
        if service is None:
            service = FleetService(app.state.settings)
            app.state.fleet = service
        return service

    def reader(request: Request):
        user, _csrf = user_of(request)
        return user

    def operator(request: Request):
        user = reader(request)
        if not can_operate(user.role):
            raise ApiError(403, "forbidden", "your role cannot change device parents")
        return user

    def client_ip(request: Request) -> str:
        return request.client.host if request.client else ""

    def record(user, request: Request, action: str, result: str, file_id: str = "", detail: str = "") -> None:
        audit = getattr(app.state, "audit", None)
        if audit is None:
            return
        audit(user, action, client_ip(request), result, app="hierarchy", file_id=file_id, detail=detail)

    @app.get("/api/v1/hierarchy")
    def hierarchy_list(request: Request):
        user = reader(request)
        service = fleet()
        report = service.hierarchy_report()
        # Auto-apply is off unless an operator turns it on. A plain page load
        # does not write when the setting is off.
        if report.get("autoApply"):
            items = proposal_items(report.get("nodes") or [])
            if items:
                results = _write(service, request, user, report, items)
                report = service.hierarchy_report(force=True)
                report["applied"] = results
        return _public(report)

    @app.get("/api/v1/hierarchy/settings")
    def hierarchy_settings(request: Request):
        reader(request)
        path, _sd = fleet()._hierarchy_paths()
        return {"autoApply": read_auto_apply(path)}

    @app.put("/api/v1/hierarchy/settings")
    async def hierarchy_settings_put(request: Request):
        user = operator(request)
        body = await _body(request)
        enabled = bool(body.get("autoApply"))
        path, _sd = fleet()._hierarchy_paths()
        write_auto_apply(path, enabled)
        fleet().cache.drop("hierarchy-report")
        record(user, request, "hierarchy-settings", "ok", detail="autoApply=%s" % enabled)
        return {"autoApply": enabled}

    @app.post("/api/v1/hierarchy/approve")
    async def hierarchy_approve(request: Request):
        user = operator(request)
        body = await _body(request)
        service = fleet()
        report = service.hierarchy_report()
        if body.get("all"):
            items = proposal_items(report.get("nodes") or [])
        else:
            items = body.get("items") or []
        if not isinstance(items, list):
            raise ApiError(400, "bad_body", "items must be a list")
        results = _write(service, request, user, report, items)
        return {"results": results}

    @app.get("/metrics/topology")
    def topology_metrics():
        report = fleet().hierarchy_report()
        return PlainTextResponse(metrics_text(report.get("nodes") or []), media_type="text/plain; version=0.0.4")

    def _write(service, request, user, report, items):
        try:
            results = service.hierarchy_write(report.get("nodes") or [], items)
        except UpstreamError as exc:
            record(user, request, "hierarchy-approve", "error", detail=exc.message)
            raise _as_upstream(exc)
        except Exception as exc:
            record(user, request, "hierarchy-approve", "error", detail=str(exc))
            raise
        for row in results:
            record(
                user,
                request,
                "hierarchy-approve",
                "ok" if row.get("ok") else "error",
                file_id=str(row.get("id") or ""),
                detail="%s parent=%s uplink=%s parent_port=%s %s" % (
                    row.get("hostname") or "",
                    row.get("parentHostname") or "",
                    row.get("uplinkInterface") or "",
                    row.get("parentInterface") or "",
                    row.get("error") or "",
                ),
            )
        return results


def _public(report: dict) -> dict:
    return {
        "autoApply": bool(report.get("autoApply")),
        "roots": list(report.get("roots") or []),
        "flagged": list(report.get("flagged") or []),
        "nodes": list(report.get("nodes") or []),
        "degraded": list(report.get("degraded") or []),
        "applied": list(report.get("applied") or []),
    }


async def _body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        raise ApiError(400, "bad_body", "body must be JSON")
    if not isinstance(body, dict):
        raise ApiError(400, "bad_body", "body must be a JSON object")
    return body
