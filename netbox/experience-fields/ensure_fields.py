#!/usr/bin/env python3
"""Create service-experience NetBox fields. Safe to run on every boot.

Creates, and does not recreate:

- site custom field vbs_server_ip (text)
- site custom field vbs_server_port (integer, default 9999)
- service custom field probe (select: icmp, tcp)
- service custom field target (text, IP or hostname when the service has no parent)
- tags third-party and bank

A second run against an unchanged NetBox does not PATCH fields that already
match. An existing description is left alone. No services or addresses are
created, so no real bank or third party is seeded. The token is never printed.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

CHOICE_SET = "IE service probe"
PROBE_CHOICES = [["icmp", "ICMP"], ["tcp", "TCP"]]


def token_from_env() -> str:
    path = os.environ.get("NETBOX_TOKEN_FILE") or ""
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as handle:
            return handle.read().strip()
    return (os.environ.get("NETBOX_TOKEN") or "").strip()


def auth_header(token: str) -> str:
    if token.startswith("nbt_"):
        return "Bearer " + token
    return "Token " + token


class Api:
    def __init__(self, base: str, token: str, opener=None):
        self.base = base.rstrip("/")
        self.token = token
        self.opener = opener or urllib.request.urlopen

    def _request(self, method: str, path: str, body=None):
        url = path if path.startswith("http") else self.base + path
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {
            "Authorization": auth_header(self.token),
            "Accept": "application/json",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self.opener(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
                status = getattr(response, "status", 200)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            return exc.code, _json(raw)
        return status, _json(raw)

    def get(self, path: str):
        return self._request("GET", path)

    def post(self, path: str, body: dict):
        return self._request("POST", path, body)

    def patch(self, path: str, body: dict):
        return self._request("PATCH", path, body)


def _json(raw: str):
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw[:200]}


def _results(body) -> list:
    if isinstance(body, dict):
        return list(body.get("results") or [])
    if isinstance(body, list):
        return body
    return []


def _first(api: Api, path: str, key: str, value: str):
    query = urllib.parse.urlencode({key: value, "limit": 5})
    status, body = api.get(path + "?" + query)
    if status >= 400:
        raise RuntimeError("%s lookup failed (%s)" % (path, status))
    for row in _results(body):
        if str(row.get(key) or "") == value or str(row.get("slug") or "") == value or str(row.get("name") or "") == value:
            return row
    return None


def ensure_choice_set(api: Api) -> int:
    found = _first(api, "/api/extras/custom-field-choice-sets/", "name", CHOICE_SET)
    if found:
        have = {str(item[0]) for item in (found.get("extra_choices") or []) if item}
        missing = [pair for pair in PROBE_CHOICES if pair[0] not in have]
        if missing:
            merged = list(found.get("extra_choices") or []) + missing
            status, _body = api.patch(
                "/api/extras/custom-field-choice-sets/%s/" % found["id"],
                {"extra_choices": merged},
            )
            if status >= 400:
                raise RuntimeError("choice set update failed (%s)" % status)
        return int(found["id"])
    status, body = api.post("/api/extras/custom-field-choice-sets/", {
        "name": CHOICE_SET,
        "extra_choices": PROBE_CHOICES,
        "description": "Blackbox probe for a third-party or bank service.",
    })
    if status >= 400 or not body.get("id"):
        raise RuntimeError("choice set create failed (%s)" % status)
    return int(body["id"])


def _types(row) -> set:
    values = row.get("object_types") or row.get("content_types") or []
    found = set()
    for item in values:
        if isinstance(item, str):
            found.add(item)
        elif isinstance(item, dict):
            app = item.get("app_label") or ""
            model = item.get("model") or ""
            if app and model:
                found.add("%s.%s" % (app, model))
    return found


def ensure_field(api: Api, spec: dict) -> str:
    """Create the field, or add an object type that is missing. Returns created|present|updated."""
    found = _first(api, "/api/extras/custom-fields/", "name", spec["name"])
    if not found:
        status, body = api.post("/api/extras/custom-fields/", spec)
        if status >= 400 or not body.get("id"):
            raise RuntimeError("custom field %s create failed (%s)" % (spec["name"], status))
        return "created"
    have = _types(found)
    want = set(spec.get("object_types") or [])
    if want and not want.issubset(have):
        status, _body = api.patch("/api/extras/custom-fields/%s/" % found["id"], {
            "object_types": sorted(have | want),
        })
        if status >= 400:
            raise RuntimeError("custom field %s update failed (%s)" % (spec["name"], status))
        return "updated"
    return "present"


def ensure_tag(api: Api, slug: str, name: str, description: str, color: str) -> str:
    found = _first(api, "/api/extras/tags/", "slug", slug)
    if found:
        return "present"
    status, body = api.post("/api/extras/tags/", {
        "name": name,
        "slug": slug,
        "color": color,
        "description": description,
    })
    if status >= 400 or not body.get("id"):
        raise RuntimeError("tag %s create failed (%s)" % (slug, status))
    return "created"


def field_specs(choice_set_id: int) -> list[dict]:
    return [
        {
            "object_types": ["dcim.site"],
            "name": "vbs_server_ip",
            "type": "text",
            "label": "VBS server IP",
            "group_name": "Service experience",
            "description": "IP or hostname of this site's VBS server. Used by IP SLA and the blackbox ping. Not a real address until an operator sets it.",
            "required": False,
            "validation_regex": r"^[A-Za-z0-9.:_-]+$",
        },
        {
            "object_types": ["dcim.site"],
            "name": "vbs_server_port",
            "type": "integer",
            "label": "VBS server port",
            "group_name": "Service experience",
            "description": "TCP port of the site VBS server. IP SLA tcp-connect and udp-jitter use it. Default 9999.",
            "required": False,
            "default": 9999,
            "validation_minimum": 1,
            "validation_maximum": 65535,
        },
        {
            "object_types": ["ipam.service"],
            "name": "probe",
            "type": "select",
            "label": "Probe",
            "group_name": "Service experience",
            "description": "Blackbox module for a service tagged third-party or bank.",
            "required": False,
            "choice_set": choice_set_id,
        },
        {
            "object_types": ["ipam.service"],
            "name": "target",
            "type": "text",
            "label": "Probe address",
            "group_name": "Service experience",
            "description": "IP or hostname to probe. Used when the service is not on a device that already has a primary IP.",
            "required": False,
            "validation_regex": r"^[A-Za-z0-9.:_-]+$",
        },
    ]


def ensure_all(api: Api) -> dict:
    choice_id = ensure_choice_set(api)
    fields = {spec["name"]: ensure_field(api, spec) for spec in field_specs(choice_id)}
    tags = {
        "third-party": ensure_tag(
            api, "third-party", "Third party",
            "Blackbox probe target. Create a service with this tag yourself. Nothing is seeded.",
            "2196f3",
        ),
        "bank": ensure_tag(
            api, "bank", "Bank",
            "Blackbox probe target for a bank. Create a service with this tag yourself. Nothing is seeded.",
            "9c27b0",
        ),
    }
    return {"choice_set": choice_id, "fields": fields, "tags": tags}


def main() -> int:
    base = (os.environ.get("NETBOX_URL") or "http://netbox:8080").rstrip("/")
    token = token_from_env()
    if not token:
        print("experience fields: no NetBox token; skipped")
        return 0
    try:
        result = ensure_all(Api(base, token))
    except Exception as exc:
        print("experience fields failed: %s" % exc.__class__.__name__)
        return 1
    print("experience fields %s" % json.dumps(result["fields"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
