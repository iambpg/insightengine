#!/usr/bin/env python3
"""Decide which Postgres volume belongs to which service.

Identification uses database and role names, never volume name order.
Exit 0 and print "destination<TAB>source" lines, or exit 2 and print why
nothing should be copied.
"""
from __future__ import annotations

import json
import re
import sys

MARKERS = (
    "netbox",
    "ie_config",
    "insightengine",
    "netdisco",
    "telegraf_data",
    "activepieces_data",
    "postgres",
    "template0",
    "template1",
)
EMPTY_ONLY = {"postgres", "template0", "template1"}
DEST = {"netbox": "netbox", "insightengine": "insightengine"}


def markers_from_bytes(blob: bytes) -> set[str]:
    text = blob.decode("latin1", errors="ignore")
    found = set()
    for name in MARKERS:
        if re.search(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])", text):
            found.add(name)
    return found


def classify(databases: list[str], roles: list[str]) -> str:
    names = {str(item) for item in list(databases) + list(roles)}
    is_nb = "netbox" in names
    is_ie = "ie_config" in names or "insightengine" in names
    is_nd = "netdisco" in names
    if is_nb and is_ie:
        return "ambiguous"
    if is_nb:
        return "netbox"
    if is_ie:
        return "insightengine"
    if is_nd:
        return "netdisco"
    interesting = names - EMPTY_ONLY
    if not interesting:
        return "empty"
    return "unknown"


def assign(volumes: list[dict], explicit: dict[str, str] | None = None) -> list[tuple[str, str]]:
    """Return [(destination, source_id), ...]. Raise SystemExit on conflict."""
    explicit = explicit or {}
    by_id = {str(item["id"]): item for item in volumes}
    chosen: dict[str, str] = {}
    used: set[str] = set()

    def content_kind(volume_id: str) -> str:
        row = by_id.get(volume_id)
        if row is None:
            return "missing"
        return classify(row.get("databases") or [], row.get("roles") or [])

    def take(dest: str, volume_id: str, why: str) -> None:
        if volume_id not in by_id and why != "map-unchecked":
            # explicit map entries are also listed in volumes when docker described them
            pass
        kind = content_kind(volume_id) if volume_id in by_id else "missing"
        if kind in ("netbox", "insightengine") and kind != dest:
            raise SystemExit(
                "refusing to map %s to %s: catalogs identify it as %s" % (volume_id, dest, kind)
            )
        if kind == "ambiguous":
            raise SystemExit("volume %s contains both netbox and ie_config catalogs; not copying" % volume_id)
        prev = chosen.get(dest)
        if prev and prev != volume_id:
            raise SystemExit("two volumes match %s (%s and %s); nothing was copied" % (dest, prev, volume_id))
        owner = [name for name, src in chosen.items() if src == volume_id]
        if owner and owner[0] != dest:
            raise SystemExit("volume %s is claimed by both %s and %s; nothing was copied" % (volume_id, owner[0], dest))
        chosen[dest] = volume_id
        used.add(volume_id)

    for dest, volume_id in explicit.items():
        if dest not in DEST:
            raise SystemExit("unknown --map destination %s" % dest)
        if not volume_id:
            raise SystemExit("--map %s has an empty volume" % dest)
        take(dest, volume_id, "map")

    # Container inspect wins over name order, and must agree with catalogs.
    for row in volumes:
        service = (row.get("container") or "").strip()
        if service in DEST and row["id"] not in used:
            take(service, row["id"], "container")

    pools: dict[str, list[str]] = {"netbox": [], "insightengine": []}
    unknowns = []
    for row in volumes:
        if row["id"] in used:
            continue
        kind = classify(row.get("databases") or [], row.get("roles") or [])
        row["kind"] = kind
        if kind in pools:
            pools[kind].append(row["id"])
        elif kind in ("empty", "netdisco"):
            continue
        else:
            unknowns.append(row["id"])

    for dest, ids in pools.items():
        if dest in chosen:
            extra = [item for item in ids if item != chosen[dest]]
            if extra:
                raise SystemExit(
                    "destination %s is already %s but content also matches %s; nothing was copied"
                    % (dest, chosen[dest], ", ".join(extra))
                )
            continue
        if len(ids) > 1:
            raise SystemExit(
                "multiple volumes look like %s (%s); nothing was copied" % (dest, ", ".join(ids))
            )
        if len(ids) == 1:
            take(dest, ids[0], "content")

    if unknowns and len(chosen) < 2:
        raise SystemExit(
            "could not identify volume(s) %s (no netbox or ie_config catalog); nothing was copied. "
            "Re-run with --map netbox=<volume>,insightengine=<volume> after checking the dry-run."
            % ", ".join(unknowns)
        )
    if unknowns and len(chosen) == 2:
        raise SystemExit(
            "identified both clusters but extra unidentified volume(s) remain (%s); nothing was copied"
            % ", ".join(unknowns)
        )
    return [(dest, chosen[dest]) for dest in ("netbox", "insightengine") if dest in chosen]


def _self_test() -> None:
    # Random-looking ids. The ie cluster sorts first on purpose.
    ie_id = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    nb_id = "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"
    volumes = [
        {
            "id": ie_id,
            "databases": ["insightengine", "ie_config", "postgres", "template0", "template1"],
            "roles": ["insightengine", "ie_config", "postgres"],
            "bytes": 100,
            "mtime": "2026-10-28T00:00:00Z",
        },
        {
            "id": nb_id,
            "databases": ["netbox", "postgres", "template0", "template1"],
            "roles": ["netbox", "postgres"],
            "bytes": 200,
            "mtime": "2026-10-28T00:00:01Z",
        },
    ]
    # Feed them sorted by id (ie id is first). Mapping must still be by content.
    ordered = sorted(volumes, key=lambda row: row["id"])
    mapping = dict(assign(ordered))
    if mapping.get("netbox") != nb_id or mapping.get("insightengine") != ie_id:
        raise SystemExit("self-test mapping %s" % mapping)

    blob_nb = b"\x00netbox\x00postgres\x00template1\x00"
    blob_ie = b"xx ie_config yy insightengine zz"
    if "netbox" not in markers_from_bytes(blob_nb) or "ie_config" not in markers_from_bytes(blob_ie):
        raise SystemExit("marker scan failed")
    if "netbox" in markers_from_bytes(b"notnetboxx"):
        raise SystemExit("marker scan matched a substring")

    swapped = [
        {"id": "vol-a", "databases": ["ie_config"], "roles": ["ie_config"]},
        {"id": "vol-b", "databases": ["netbox"], "roles": ["netbox"]},
    ]
    again = dict(assign(list(reversed(swapped))))
    if again != {"netbox": "vol-b", "insightengine": "vol-a"}:
        raise SystemExit("reversed order mapping %s" % again)

    try:
        assign([
            {"id": "1", "databases": ["netbox"], "roles": ["netbox"]},
            {"id": "2", "databases": ["netbox"], "roles": ["netbox"]},
        ])
    except SystemExit as exc:
        if "multiple volumes" not in str(exc):
            raise
    else:
        raise SystemExit("duplicate netbox clusters were accepted")

    try:
        assign([
            {"id": "1", "databases": ["mystery"], "roles": ["mystery"]},
        ])
    except SystemExit as exc:
        if "could not identify" not in str(exc):
            raise
    else:
        raise SystemExit("unknown cluster was accepted")

    forced = dict(assign(
        [{"id": "abc", "databases": ["mysterydb"], "roles": []}],
        {"netbox": "abc"},
    ))
    if forced.get("netbox") != "abc":
        raise SystemExit("explicit map failed: %s" % forced)
    try:
        assign(
            [{"id": "abc", "databases": ["ie_config"], "roles": ["ie_config"]}],
            {"netbox": "abc"},
        )
    except SystemExit as exc:
        if "identify it as insightengine" not in str(exc):
            raise
    else:
        raise SystemExit("map contradicting catalogs was accepted")

    container = dict(assign([
        {"id": "from-inspect-nb", "databases": ["netbox"], "roles": ["netbox"], "container": "netbox"},
        {"id": "from-inspect-ie", "databases": ["ie_config"], "roles": ["ie_config"], "container": "insightengine"},
    ]))
    if container["netbox"] != "from-inspect-nb" or container["insightengine"] != "from-inspect-ie":
        raise SystemExit("container mapping failed: %s" % container)
    print("PASS  migrate matches clusters by catalog, not by volume name")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        _self_test()
        sys.exit(0)
    payload = json.load(sys.stdin)
    try:
        pairs = assign(payload.get("volumes") or [], payload.get("map") or {})
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    for dest, source in pairs:
        print("%s\t%s" % (dest, source))
