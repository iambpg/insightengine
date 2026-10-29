#!/usr/bin/env python3
"""Create NetBox components that a device type defines but the device lacks.

NetBox copies component templates onto a device only when the device is
created. Templates added later, or components deleted by hand, are not filled
in. This walks every device and creates the missing ones. The match key is
the component name.

- An existing component is left as it is. Nothing is deleted, renamed, or
  edited, including a custom component whose name is not in the templates.
- A device whose device type has no component templates is skipped. Discovery
  stub types are the usual case.
- A front port's rear_ports mapping uses the rear port on that device with
  the same name as the template's rear port. The template id is not copied.
- A power outlet's power_port and an interface's bridge are resolved the
  same way, by name on the device.
- One bad device or component is recorded and the walk continues.

A second run against an unchanged NetBox creates nothing.

Env (the token is never printed):
  NETBOX_URL                    default http://netbox:8080
  NETBOX_TOKEN_FILE             file holding the API token (v2: nbt_<key>.<secret>)
  NETBOX_TOKEN                  alternative to the file
  NETBOX_BACKFILL_COMPONENTS    default true; false, 0, no, or off skips the run
"""
import argparse
import json
import os
import sys
import time

KINDS = (
    "console-ports",
    "console-server-ports",
    "power-ports",
    "power-outlets",
    "interfaces",
    "rear-ports",
    "front-ports",
    "module-bays",
    "device-bays",
)
# Scalar fields copied onto a new component. Relations are resolved separately
# so a template id is never written onto the device.
COPY_FIELDS = {
    "console-ports": ("name", "label", "type", "description"),
    "console-server-ports": ("name", "label", "type", "description"),
    "power-ports": ("name", "label", "type", "maximum_draw", "allocated_draw", "description"),
    "power-outlets": ("name", "label", "type", "feed_leg", "description", "color"),
    "interfaces": ("name", "label", "type", "enabled", "mgmt_only", "description", "poe_mode", "poe_type", "rf_role"),
    "rear-ports": ("name", "label", "type", "positions", "color", "description"),
    "front-ports": ("name", "label", "type", "positions", "color", "description"),
    "module-bays": ("name", "label", "position", "enabled", "description"),
    "device-bays": ("name", "label", "enabled", "description"),
}
TEMPLATE_PATH = {
    "console-ports": "/api/dcim/console-port-templates/",
    "console-server-ports": "/api/dcim/console-server-port-templates/",
    "power-ports": "/api/dcim/power-port-templates/",
    "power-outlets": "/api/dcim/power-outlet-templates/",
    "interfaces": "/api/dcim/interface-templates/",
    "rear-ports": "/api/dcim/rear-port-templates/",
    "front-ports": "/api/dcim/front-port-templates/",
    "module-bays": "/api/dcim/module-bay-templates/",
    "device-bays": "/api/dcim/device-bay-templates/",
}
COMPONENT_PATH = {
    "console-ports": "/api/dcim/console-ports/",
    "console-server-ports": "/api/dcim/console-server-ports/",
    "power-ports": "/api/dcim/power-ports/",
    "power-outlets": "/api/dcim/power-outlets/",
    "interfaces": "/api/dcim/interfaces/",
    "rear-ports": "/api/dcim/rear-ports/",
    "front-ports": "/api/dcim/front-ports/",
    "module-bays": "/api/dcim/module-bays/",
    "device-bays": "/api/dcim/device-bays/",
}
DISABLED = {"0", "false", "no", "off"}


def backfill_enabled(value=None):
    raw = os.environ.get("NETBOX_BACKFILL_COMPONENTS", "true") if value is None else value
    return str(raw).strip().lower() not in DISABLED


def related_name(value, names_by_id):
    """Name of a related template. An int is a template id; a string is a name."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return names_by_id.get(value)
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        name = value.get("name")
        if isinstance(name, str) and name:
            return name
        ident = value.get("id")
        if isinstance(ident, int):
            return names_by_id.get(ident)
    return None


def device_type_id(device):
    dtype = device.get("device_type") if isinstance(device, dict) else None
    if isinstance(dtype, dict):
        ident = dtype.get("id")
        return ident if isinstance(ident, int) else None
    if isinstance(dtype, int):
        return dtype
    return None


def device_label(device):
    name = device.get("name") if isinstance(device, dict) else None
    if isinstance(name, str) and name:
        return name
    return "device-%s" % (device.get("id") if isinstance(device, dict) else "?")


def new_stats(dry_run):
    return {
        "devices_scanned": 0,
        "devices_skipped": 0,
        "devices_changed": 0,
        "created": {kind: 0 for kind in KINDS},
        "failures": [],
        "dry_run": bool(dry_run),
    }


def fail(stats, device, kind, message):
    stats["failures"].append({
        "device": device,
        "kind": kind,
        "error": str(message)[:500],
    })


def summary_payload(stats):
    payload = {
        "devices_scanned": stats["devices_scanned"],
        "devices_skipped": stats["devices_skipped"],
        "devices_changed": stats["devices_changed"],
        "created": stats["created"],
        "failures": len(stats["failures"]) if isinstance(stats["failures"], list) else stats["failures"],
        "dry_run": bool(stats.get("dry_run")),
    }
    if "seconds" in stats:
        payload["seconds"] = stats["seconds"]
    if stats.get("disabled"):
        payload["disabled"] = True
    return payload


def plain(value):
    """NetBox choice fields are returned as {"value", "label"}. Writes want the value."""
    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return value


def _copy_scalars(kind, template):
    body = {}
    for key in COPY_FIELDS[kind]:
        if key not in template:
            continue
        value = plain(template[key])
        if value is None or value == "":
            continue
        body[key] = value
    return body


def _front_mappings(template, rear_names, rear_ids):
    """Map each template rear port to the device rear port of the same name."""
    raw = template.get("rear_ports")
    items = raw if isinstance(raw, list) and raw else None
    if items is None and template.get("rear_port"):
        items = [{
            "position": 1,
            "rear_port": template.get("rear_port"),
            "rear_port_position": template.get("rear_port_position") or 1,
        }]
    if not items:
        return []
    mappings = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("front port %s has a mapping that is not an object" % template.get("name"))
        rear_name = related_name(item.get("rear_port"), rear_names)
        if not rear_name:
            raise ValueError("front port %s mapping has no rear port name" % template.get("name"))
        rear_id = rear_ids.get(rear_name)
        if rear_id is None:
            raise ValueError("device has no rear port named %s" % rear_name)
        position = item.get("position") or 1
        rear_position = item.get("rear_port_position") or 1
        mappings.append({
            "position": position,
            "rear_port": rear_id,
            "rear_port_position": rear_position,
        })
    return mappings


def build_body(kind, template, device_id, indexes, names):
    body = _copy_scalars(kind, template)
    if not body.get("name"):
        raise ValueError("template has no name")
    body["device"] = device_id
    if kind == "power-outlets" and template.get("power_port"):
        port_name = related_name(template.get("power_port"), names["power-ports"])
        if not port_name:
            raise ValueError("power outlet %s power port has no name" % body["name"])
        port_id = indexes["power-ports"].get(port_name)
        if port_id is None:
            raise ValueError("device has no power port named %s" % port_name)
        body["power_port"] = port_id
    elif kind == "interfaces" and template.get("bridge"):
        bridge_name = related_name(template.get("bridge"), names["interfaces"])
        if not bridge_name:
            raise ValueError("interface %s bridge has no name" % body["name"])
        bridge_id = indexes["interfaces"].get(bridge_name)
        if bridge_id is None:
            raise ValueError("device has no interface named %s" % bridge_name)
        body["bridge"] = bridge_id
    elif kind == "front-ports":
        mappings = _front_mappings(template, names["rear-ports"], indexes["rear-ports"])
        if mappings:
            body["rear_ports"] = mappings
    return body


class _DryIds:
    def __init__(self):
        self.value = -1

    def next(self):
        current = self.value
        self.value -= 1
        return current


def create_components(client, kind, rows, stats, device, dry_ids):
    """POST missing components. A bad row is recorded; the rest are still created."""
    if not rows:
        return []
    if stats["dry_run"]:
        made = []
        for row in rows:
            item = dict(row)
            item["id"] = dry_ids.next()
            made.append(item)
        stats["created"][kind] += len(rows)
        return made
    path = COMPONENT_PATH[kind]
    made = []
    for offset in range(0, len(rows), 100):
        chunk = rows[offset:offset + 100]
        response = None
        error = None
        try:
            response = client.req("POST", path, chunk)
        except Exception as exc:
            error = repr(exc)
        if response is not None and response.status_code == 201:
            body = response.json()
            if isinstance(body, dict):
                body = [body]
            if isinstance(body, list):
                made.extend(body)
                stats["created"][kind] += len(body)
                continue
            error = "unexpected create response"
        if len(chunk) == 1 and response is not None:
            fail(stats, device, kind, error or response.text)
            continue
        for row in chunk:
            try:
                one = client.req("POST", path, row)
            except Exception as exc:
                fail(stats, device, kind, "%s: %s" % (row.get("name"), repr(exc)))
                continue
            if one.status_code == 201:
                made.append(one.json())
                stats["created"][kind] += 1
            else:
                fail(stats, device, kind, "%s: %s" % (row.get("name"), one.text))
    return made


def _remember(index, objects, sent):
    for pos, obj in enumerate(objects):
        if not isinstance(obj, dict):
            continue
        name = obj.get("name")
        if not name and pos < len(sent):
            name = sent[pos].get("name")
        ident = obj.get("id")
        if name and ident is not None:
            index[name] = ident


def _missing(templates, index):
    missing = []
    seen = set(index)
    for template in templates:
        name = template.get("name") if isinstance(template, dict) else None
        if not isinstance(name, str) or not name:
            continue
        if name in seen:
            continue
        seen.add(name)
        missing.append(template)
    return missing


def _create_kind(client, kind, templates, device_id, device, indexes, names, stats, dry_ids):
    missing = _missing(templates, indexes[kind])
    if kind != "interfaces":
        rows = []
        for template in missing:
            try:
                rows.append(build_body(kind, template, device_id, indexes, names))
            except ValueError as exc:
                fail(stats, device, kind, exc)
        made = create_components(client, kind, rows, stats, device, dry_ids)
        _remember(indexes[kind], made, rows)
        return
    pending = list(missing)
    while pending:
        pending_names = {item.get("name") for item in pending}
        ready = []
        later = []
        for template in pending:
            bridge = template.get("bridge")
            if not bridge:
                ready.append(template)
                continue
            bridge_name = related_name(bridge, names["interfaces"])
            if bridge_name and bridge_name in indexes["interfaces"]:
                ready.append(template)
            elif bridge_name and bridge_name in pending_names:
                later.append(template)
            else:
                fail(stats, device, kind, "interface %s bridge %s is not on the device" % (
                    template.get("name"), bridge_name or "?"))
        if not ready:
            for template in later:
                fail(stats, device, kind, "interface %s bridge could not be ordered" % template.get("name"))
            return
        rows = []
        for template in ready:
            try:
                rows.append(build_body(kind, template, device_id, indexes, names))
            except ValueError as exc:
                fail(stats, device, kind, exc)
        made = create_components(client, kind, rows, stats, device, dry_ids)
        _remember(indexes["interfaces"], made, rows)
        pending = later


def _for_device_type(rows, device_type):
    kept = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        module_type = row.get("module_type")
        if module_type:
            continue
        owner = row.get("device_type")
        if isinstance(owner, dict) and owner.get("id") not in (None, device_type):
            continue
        if isinstance(owner, int) and owner != device_type:
            continue
        kept.append(row)
    return kept


def load_templates(client, device_type):
    loaded = {}
    total = 0
    for kind in KINDS:
        rows = _for_device_type(
            client.list_all(TEMPLATE_PATH[kind], {"device_type_id": device_type}),
            device_type,
        )
        loaded[kind] = rows
        total += len(rows)
    loaded["count"] = total
    loaded["names"] = {
        "rear-ports": {row["id"]: row["name"] for row in loaded["rear-ports"] if row.get("id") is not None},
        "interfaces": {row["id"]: row["name"] for row in loaded["interfaces"] if row.get("id") is not None},
        "power-ports": {row["id"]: row["name"] for row in loaded["power-ports"] if row.get("id") is not None},
    }
    return loaded


def backfill_device(client, device, cache, stats, dry_ids):
    label = device_label(device)
    dtype = device_type_id(device)
    device_id = device.get("id") if isinstance(device, dict) else None
    if not isinstance(device_id, int) or dtype is None:
        fail(stats, label, "device", "device has no id or device type")
        return
    if dtype not in cache:
        cache[dtype] = load_templates(client, dtype)
    templates = cache[dtype]
    if not templates["count"]:
        stats["devices_skipped"] += 1
        return
    indexes = {}
    for kind in KINDS:
        rows = client.list_all(COMPONENT_PATH[kind], {"device_id": device_id, "brief": 1})
        indexes[kind] = {}
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("name"), str) and row.get("name"):
                indexes[kind][row["name"]] = row.get("id")
    before = sum(stats["created"].values())
    for kind in KINDS:
        _create_kind(
            client, kind, templates[kind], device_id, label,
            indexes, templates["names"], stats, dry_ids,
        )
    if sum(stats["created"].values()) > before:
        stats["devices_changed"] += 1


def backfill(client, dry_run=False):
    """Create missing components for every device. Returns the stats dict."""
    stats = new_stats(dry_run)
    dry_ids = _DryIds()
    cache = {}
    try:
        devices = client.list_all("/api/dcim/devices/")
    except Exception as exc:
        fail(stats, "", "devices", repr(exc))
        return stats
    for device in devices:
        stats["devices_scanned"] += 1
        if not isinstance(device, dict):
            fail(stats, "", "device", "device row is not an object")
            continue
        try:
            backfill_device(client, device, cache, stats, dry_ids)
        except Exception as exc:
            fail(stats, device_label(device), "device", repr(exc))
        scanned = stats["devices_scanned"]
        if scanned % 200 == 0:
            print("scanned %s" % scanned, flush=True)
    return stats


class NB:
    def __init__(self, url, token):
        import requests
        self.requests = requests
        self.url = url.rstrip("/")
        self.session = requests.Session()
        scheme = "Bearer " if token.startswith("nbt_") else "Token "
        self.session.headers.update({
            "Authorization": scheme + token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def req(self, method, path, body=None, params=None):
        for attempt in range(8):
            try:
                response = self.session.request(method, self.url + path, json=body, params=params, timeout=120)
            except self.requests.RequestException:
                time.sleep(min(2 ** attempt, 30))
                continue
            if response.status_code == 429 or response.status_code >= 500:
                time.sleep(float(response.headers.get("Retry-After", min(2 ** attempt, 30))))
                continue
            return response
        raise RuntimeError("NetBox unreachable or rate limited: %s %s" % (method, path))

    def list_all(self, path, params=None):
        out = []
        query = dict(params or {}, limit=1000)
        nxt = self.url + path
        while nxt:
            response = self.req("GET", nxt[len(self.url):] if nxt.startswith(self.url) else nxt, params=query)
            response.raise_for_status()
            body = response.json()
            out += body["results"]
            nxt = body.get("next")
            query = None
        return out


def read_token():
    """Read the token on every attempt so a provisioned file is picked up without a restart."""
    path = os.environ.get("NETBOX_TOKEN_FILE") or ""
    if path:
        try:
            with open(path, encoding="utf-8") as handle:
                value = handle.read().strip()
            if value and value != "unset-placeholder":
                return value
        except OSError:
            pass
    return (os.environ.get("NETBOX_TOKEN") or "").strip()


def _disabled_stats(dry_run):
    stats = new_stats(dry_run)
    stats["disabled"] = True
    return stats


def main(argv=None):
    parser = argparse.ArgumentParser(description="Create missing NetBox device components from templates")
    parser.add_argument("--dry-run", action="store_true", help="report what would be created and write nothing")
    parser.add_argument("--wait", type=int, default=600, help="seconds to wait for the NetBox API")
    parser.add_argument("--report", default=os.environ.get("REPORT", "/tmp/component-backfill-report.json"))
    parser.add_argument("--strict", action="store_true", help="exit 1 if any device or component failed")
    args = parser.parse_args(argv)
    if not backfill_enabled():
        stats = _disabled_stats(args.dry_run)
        print(json.dumps(summary_payload(stats)), flush=True)
        return 0
    url = os.environ.get("NETBOX_URL", "http://netbox:8080")
    client = None
    started = time.time()
    while True:
        token = read_token()
        if not token:
            print("NetBox token file is empty; retrying", flush=True)
        else:
            client = NB(url, token)
            try:
                response = client.req("GET", "/api/dcim/devices/", params={"limit": 1})
                if response.status_code == 200:
                    break
                print("NetBox answered %s (token invalid or not ready); retrying" % response.status_code, flush=True)
            except Exception as exc:
                print("waiting for NetBox:", exc.__class__.__name__, flush=True)
        if time.time() - started > args.wait:
            print("NetBox not usable after %ss" % args.wait, flush=True)
            return 1
        time.sleep(5)
    stats = backfill(client, dry_run=args.dry_run)
    stats["seconds"] = round(time.time() - started, 1)
    try:
        with open(args.report, "w", encoding="utf-8") as handle:
            json.dump(stats, handle, indent=1)
    except OSError as exc:
        fail(stats, "", "report", exc)
    print(json.dumps(summary_payload(stats)), flush=True)
    if args.strict and stats["failures"]:
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("component backfill error:", exc.__class__.__name__, flush=True)
        sys.exit(1)
