#!/usr/bin/env python3
"""Idempotent NetBox region loader.

Reads regions.yaml and ensures each dcim.region exists. The match key is the
slug.

- Missing slug: create name, slug, parent, and description.
- Existing slug: update name and parent when they differ. Description and every
  other field are left alone, so an operator edit to the description is kept.
- Regions that are not in the file are not deleted.

A second run against an unchanged NetBox creates nothing and updates nothing.

Env (the token is never printed):
  NETBOX_URL         default http://netbox:8080
  NETBOX_TOKEN_FILE  file holding the API token (v2: nbt_<key>.<secret>)
  NETBOX_TOKEN       alternative to the file
  REGIONS_FILE       default /data/regions.yaml
"""
import argparse
import json
import os
import re
import sys
import time

import yaml

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def validate_regions(regions):
    """Return a list of problems. Empty means the catalog is safe to load."""
    errors = []
    if not isinstance(regions, list) or not regions:
        return ["regions must be a non-empty list"]
    seen = set()
    by_slug = {}
    for index, row in enumerate(regions):
        if not isinstance(row, dict):
            errors.append("region %s is not a mapping" % index)
            continue
        slug = row.get("slug")
        name = row.get("name")
        parent = row.get("parent")
        description = row.get("description", "")
        where = slug if isinstance(slug, str) and slug else ("#%s" % index)
        if not isinstance(slug, str) or not SLUG_RE.fullmatch(slug) or len(slug) > 100:
            errors.append("%s has an invalid slug" % where)
        elif slug in seen:
            errors.append("duplicate slug %s" % slug)
        else:
            seen.add(slug)
            by_slug[slug] = row
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            errors.append("%s has an invalid name" % where)
        if parent is not None and not isinstance(parent, str):
            errors.append("%s parent must be a slug or null" % where)
        if parent == slug:
            errors.append("%s is its own parent" % where)
        if not isinstance(description, str) or len(description) > 200:
            errors.append("%s has an invalid description" % where)
    known = set(by_slug)
    for row in regions:
        if not isinstance(row, dict):
            continue
        parent = row.get("parent")
        slug = row.get("slug")
        label = slug if isinstance(slug, str) and slug else "?"
        if isinstance(parent, str) and parent not in known:
            errors.append("%s parent %s does not exist" % (label, parent))
    for slug, row in by_slug.items():
        seen_path = set()
        cursor = slug
        while cursor:
            if cursor in seen_path:
                errors.append("cycle at %s" % slug)
                break
            seen_path.add(cursor)
            parent = by_slug.get(cursor, {}).get("parent") if cursor in by_slug else None
            cursor = parent
    return errors


def load_regions(path):
    with open(path, encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    if not isinstance(document, dict) or not isinstance(document.get("regions"), list):
        raise ValueError("regions file must be a mapping with a regions list")
    regions = []
    for row in document["regions"]:
        regions.append({
            "slug": row.get("slug") if isinstance(row, dict) else None,
            "name": row.get("name") if isinstance(row, dict) else None,
            "parent": row.get("parent") if isinstance(row, dict) else None,
            "description": (row.get("description") if isinstance(row, dict) else None) or "",
        })
    errors = validate_regions(regions)
    if errors:
        raise ValueError("; ".join(errors))
    return regions


def parent_id(row):
    parent = row.get("parent") if isinstance(row, dict) else None
    if not parent:
        return None
    if isinstance(parent, dict):
        value = parent.get("id")
    elif isinstance(parent, int) or (isinstance(parent, str) and parent.isdigit()):
        value = parent
    else:
        return None
    return int(value) if value is not None else None


def waves(regions):
    """Parent before child. validate_regions has already rejected cycles."""
    pending = list(regions)
    done = set()
    while pending:
        ready = []
        rest = []
        for spec in pending:
            parent = spec.get("parent")
            if not parent or parent in done:
                ready.append(spec)
            else:
                rest.append(spec)
        if not ready:
            raise ValueError("regions could not be ordered; a parent is missing")
        yield ready
        done.update(spec["slug"] for spec in ready)
        pending = rest


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


def _fail(stats, slug, message):
    stats["failures"].append({"slug": slug, "error": str(message)[:500]})


def sync_regions(client, regions):
    """Create missing regions and sync name/parent. Never deletes. Returns counts."""
    stats = {
        "regions_created": 0,
        "regions_updated": 0,
        "regions_unchanged": 0,
        "failures": [],
    }
    existing = {row["slug"]: row for row in client.list_all("/api/dcim/regions/")}
    ids = {row["slug"]: int(row["id"]) for row in existing.values()}
    for wave in waves(regions):
        for spec in wave:
            parent = spec.get("parent")
            wanted_parent = ids.get(parent) if parent else None
            if parent and wanted_parent is None:
                _fail(stats, spec["slug"], "parent %s has no id" % parent)
                continue
            found = existing.get(spec["slug"])
            if not found:
                body = {
                    "name": spec["name"],
                    "slug": spec["slug"],
                    "description": spec.get("description") or "",
                    "parent": wanted_parent,
                }
                response = client.req("POST", "/api/dcim/regions/", body)
                if response.status_code != 201:
                    _fail(stats, spec["slug"], response.text)
                    continue
                created = response.json()
                existing[spec["slug"]] = created
                ids[spec["slug"]] = int(created["id"])
                stats["regions_created"] += 1
                if stats["regions_created"] % 100 == 0:
                    print("created %s" % stats["regions_created"], flush=True)
                continue
            patch = {}
            if found.get("name") != spec["name"]:
                patch["name"] = spec["name"]
            if parent_id(found) != wanted_parent:
                patch["parent"] = wanted_parent
            if not patch:
                ids[spec["slug"]] = int(found["id"])
                stats["regions_unchanged"] += 1
                continue
            response = client.req("PATCH", "/api/dcim/regions/%s/" % found["id"], patch)
            if response.status_code != 200:
                _fail(stats, spec["slug"], response.text)
                continue
            updated = response.json()
            existing[spec["slug"]] = updated
            ids[spec["slug"]] = int(updated["id"])
            stats["regions_updated"] += 1
    return stats


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default=os.environ.get("REGIONS_FILE", "/data/regions.yaml"))
    parser.add_argument("--wait", type=int, default=600, help="seconds to wait for the NetBox API")
    parser.add_argument("--report", default=os.environ.get("REPORT", "/tmp/region-import-report.json"))
    parser.add_argument("--strict", action="store_true", help="exit 1 if any entry failed")
    args = parser.parse_args()
    try:
        regions = load_regions(args.file)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print("regions file:", exc, flush=True)
        return 1
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
                response = client.req("GET", "/api/dcim/regions/", params={"limit": 1})
                if response.status_code == 200:
                    break
                print("NetBox answered %s (token invalid or not ready); retrying" % response.status_code, flush=True)
            except Exception as exc:
                print("waiting for NetBox:", exc.__class__.__name__, flush=True)
        if time.time() - started > args.wait:
            print("NetBox not usable after %ss" % args.wait, flush=True)
            return 1
        time.sleep(5)
    stats = sync_regions(client, regions)
    stats["seconds"] = round(time.time() - started, 1)
    with open(args.report, "w", encoding="utf-8") as handle:
        json.dump(stats, handle, indent=1)
    summary = {key: (value if key != "failures" else len(value)) for key, value in stats.items()}
    print(json.dumps(summary), flush=True)
    if stats["failures"] and args.strict:
        return 1
    if stats["failures"]:
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("regions import error:", exc.__class__.__name__, flush=True)
        sys.exit(1)
