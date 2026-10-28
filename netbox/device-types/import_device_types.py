#!/usr/bin/env python3
"""Idempotent NetBox device-type / module-type importer.

Reads <library>/device-types/<Vendor>/*.yaml and <library>/module-types/<Vendor>/*.yaml
from the vendored netbox-community/devicetype-library snapshot (see library/SOURCE)
and creates manufacturers, device types, module types and component templates.
Re-running it only creates what is missing.

The Palo Alto manufacturer slug is forced to palo-alto so it matches
config/discovery/module-map.yml and sysobjectid-map.yml.

Env (the token is never printed):
  NETBOX_URL         default http://netbox:8080
  NETBOX_TOKEN_FILE  file holding the API token (v2: nbt_<key>.<secret>)
  NETBOX_TOKEN       alternative to the file
"""
import argparse
import glob
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests
import yaml

SLUG_OVERRIDES = {"Palo Alto Networks": "palo-alto", "Cisco": "cisco", "Fortinet": "fortinet"}

DT_FIELDS = (
    "part_number", "u_height", "exclude_from_utilization", "is_full_depth", "subdevice_role",
    "airflow", "weight", "weight_unit", "description", "comments",
)
MT_FIELDS = ("part_number", "weight", "weight_unit", "description", "comments", "airflow", "attribute_data")
COMPONENTS = [
    ("interfaces", "interface-templates", ("name", "label", "type", "enabled", "mgmt_only", "description", "poe_mode", "poe_type", "bridge", "rf_role")),
    ("console-ports", "console-port-templates", ("name", "label", "type", "description")),
    ("console-server-ports", "console-server-port-templates", ("name", "label", "type", "description")),
    ("power-ports", "power-port-templates", ("name", "label", "type", "maximum_draw", "allocated_draw", "description")),
    ("power-outlets", "power-outlet-templates", ("name", "label", "type", "power_port", "feed_leg", "description")),
    ("rear-ports", "rear-port-templates", ("name", "label", "type", "positions", "description")),
    ("front-ports", "front-port-templates", ("name", "label", "type", "rear_port", "rear_port_position", "description")),
    ("module-bays", "module-bay-templates", ("name", "label", "position", "description")),
    ("device-bays", "device-bay-templates", ("name", "label", "description")),
]
lock = threading.Lock()
stats = {
    "manufacturers_created": 0, "device_types_created": 0, "device_types_existing": 0,
    "module_types_created": 0, "module_types_existing": 0, "templates_created": 0, "failures": [],
}


class NB:
    def __init__(self, url, token):
        self.url = url.rstrip("/")
        self.s = requests.Session()
        scheme = "Bearer " if token.startswith("nbt_") else "Token "
        self.s.headers.update({
            "Authorization": scheme + token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def req(self, method, path, body=None, params=None):
        for attempt in range(8):
            try:
                response = self.s.request(method, self.url + path, json=body, params=params, timeout=120)
            except requests.RequestException:
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


def pick(src, fields):
    return {key: src[key] for key in fields if key in src and src[key] not in (None, "")}


def fail(kind, name, msg):
    with lock:
        stats["failures"].append({"kind": kind, "name": name, "error": str(msg)[:500]})


def ensure_templates(nb, parent_key, parent_id, doc, label, existing):
    for ykey, endpoint, fields in COMPONENTS:
        items = doc.get(ykey) or []
        if not items:
            continue
        have = set()
        if existing:
            have = {row["name"] for row in nb.list_all("/api/dcim/%s/" % endpoint, {parent_key + "_id": parent_id})}
        rows = []
        for item in items:
            if item.get("name") in have:
                continue
            row = pick(item, fields)
            row[parent_key] = parent_id
            rows.append(row)
        if ykey == "front-ports" and rows:
            rear = {row["name"]: row["id"] for row in nb.list_all("/api/dcim/rear-port-templates/", {parent_key + "_id": parent_id})}
            for row in rows:
                if isinstance(row.get("rear_port"), str) and row["rear_port"] in rear:
                    row["rear_port"] = rear[row["rear_port"]]
        if ykey == "power-outlets" and rows:
            ports = {row["name"]: row["id"] for row in nb.list_all("/api/dcim/power-port-templates/", {parent_key + "_id": parent_id})}
            for row in rows:
                if isinstance(row.get("power_port"), str) and row["power_port"] in ports:
                    row["power_port"] = ports[row["power_port"]]
        for offset in range(0, len(rows), 200):
            chunk = rows[offset:offset + 200]
            response = nb.req("POST", "/api/dcim/%s/" % endpoint, chunk)
            if response.status_code == 201:
                with lock:
                    stats["templates_created"] += len(chunk)
            else:
                for row in chunk:
                    one = nb.req("POST", "/api/dcim/%s/" % endpoint, row)
                    if one.status_code == 201:
                        with lock:
                            stats["templates_created"] += 1
                    else:
                        fail(endpoint, "%s / %s" % (label, row.get("name")), one.text)


def handle(nb, kind, path, fields, manufacturer_id, existing_by_key, filename):
    try:
        with open(filename, encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)
        model = doc["model"]
        key = (doc.get("slug") or model).lower() if kind == "device_type" else model
        found = existing_by_key.get(key if kind == "device_type" else model)
        if found:
            with lock:
                stats["device_types_existing" if kind == "device_type" else "module_types_existing"] += 1
            parent_id, existed = found["id"], True
        else:
            body = pick(doc, fields)
            body.update(manufacturer=manufacturer_id, model=model)
            if kind == "device_type":
                body["slug"] = doc["slug"]
            response = nb.req("POST", path, body)
            if response.status_code != 201:
                return fail(kind, os.path.relpath(filename), response.text)
            parent_id, existed = response.json()["id"], False
            with lock:
                stats["device_types_created" if kind == "device_type" else "module_types_created"] += 1
        ensure_templates(nb, kind, parent_id, doc, model, existed)
    except Exception as exc:  # one bad file must not stop the vendor
        fail(kind, os.path.relpath(filename), repr(exc))
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", default=os.environ.get("LIBRARY_DIR", "/library"))
    parser.add_argument("--vendors", default=os.environ.get("VENDORS", "Cisco,Fortinet,Palo Alto Networks"))
    parser.add_argument("--no-modules", action="store_true")
    parser.add_argument("--workers", type=int, default=int(os.environ.get("WORKERS", "4")))
    parser.add_argument("--wait", type=int, default=600, help="seconds to wait for the NetBox API")
    parser.add_argument("--report", default=os.environ.get("REPORT", "/tmp/import-report.json"))
    parser.add_argument("--strict", action="store_true", help="exit 1 if any entry failed")
    args = parser.parse_args()
    if os.environ.get("NETBOX_TOKEN"):
        token = os.environ["NETBOX_TOKEN"].strip()
    else:
        with open(os.environ["NETBOX_TOKEN_FILE"], encoding="utf-8") as fh:
            token = fh.read().strip()
    client = NB(os.environ.get("NETBOX_URL", "http://netbox:8080"), token)
    started = time.time()
    while True:
        try:
            response = client.req("GET", "/api/dcim/manufacturers/", params={"limit": 1})
            if response.status_code == 200:
                break
            print("NetBox answered %s (token invalid or not ready); retrying" % response.status_code, flush=True)
        except Exception as exc:
            print("waiting for NetBox:", exc.__class__.__name__, flush=True)
        if time.time() - started > args.wait:
            print("NetBox not usable after %ss" % args.wait, flush=True)
            return 1
        time.sleep(5)
    for vendor in [item.strip() for item in args.vendors.split(",") if item.strip()]:
        slug = SLUG_OVERRIDES.get(vendor) or vendor.lower().replace(" ", "-")
        got = client.list_all("/api/dcim/manufacturers/", {"slug": slug})
        if got:
            manufacturer = got[0]
        else:
            response = client.req("POST", "/api/dcim/manufacturers/", {"name": vendor, "slug": slug})
            if response.status_code != 201:
                fail("manufacturer", vendor, response.text)
                continue
            manufacturer = response.json()
            stats["manufacturers_created"] += 1
        device_types = {
            row["slug"].lower(): row
            for row in client.list_all("/api/dcim/device-types/", {"manufacturer_id": manufacturer["id"]})
        }
        files = sorted(glob.glob(os.path.join(args.library, "device-types", vendor, "*.y*ml")))
        with ThreadPoolExecutor(args.workers) as pool:
            list(pool.map(
                lambda filename: handle(client, "device_type", "/api/dcim/device-types/", DT_FIELDS, manufacturer["id"], device_types, filename),
                files,
            ))
        if not args.no_modules:
            module_types = {
                row["model"]: row
                for row in client.list_all("/api/dcim/module-types/", {"manufacturer_id": manufacturer["id"]})
            }
            files = sorted(glob.glob(os.path.join(args.library, "module-types", vendor, "*.y*ml")))
            with ThreadPoolExecutor(args.workers) as pool:
                list(pool.map(
                    lambda filename: handle(client, "module_type", "/api/dcim/module-types/", MT_FIELDS, manufacturer["id"], module_types, filename),
                    files,
                ))
        print("done vendor %s" % vendor, flush=True)
    stats["seconds"] = round(time.time() - started, 1)
    with open(args.report, "w", encoding="utf-8") as fh:
        json.dump(stats, fh, indent=1)
    summary = {key: (value if key != "failures" else len(value)) for key, value in stats.items()}
    print(json.dumps(summary), flush=True)
    if args.strict and stats["failures"]:
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("device-types import error:", exc.__class__.__name__, flush=True)
        sys.exit(1)
