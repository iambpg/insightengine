"""Dry-run plans. These functions do not talk to NetBox or Netdisco.

A plan never contains a delete, a rename, or a blind overwrite of site, role,
or rack. Apply rejects anything else before the first write.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from ie_config.hostnames import strip_hostname

from .match import build_index, host_ip, match_one, names_differ, norm_serial

SAFE_OPS = {
    "create_vc",
    "create_device",
    "attach_vc",
    "ensure_interface",
    "assign_ip",
    "set_primary_if_empty",
    "set_coords",
    "ensure_custom_field",
    "set_custom_fields",
}
PATCH_FIELDS = {"virtual_chassis", "vc_position", "primary_ip4"}
EOX_FIELDS = (
    "eox_end_of_sale",
    "eox_end_of_sw_maintenance",
    "eox_end_of_security",
    "eox_last_date_of_support",
    "eox_migration_pid",
)
_SWITCH_MEMBER = __import__("re").compile(r"(?i)^switch\s*(\d+)$")
_WLC = __import__("re").compile(r"(?i)(wireless\s*lan\s*controller|\bc9800|\bair-ct|\bwlc\b|catalyst\s*9800)")


class UnsafeChange(ValueError):
    pass


def paginate(rows: list, page, page_size, q: str, fields: list[str]) -> dict:
    needle = (q or "").strip().lower()
    chosen = rows
    if needle:
        chosen = []
        for row in rows:
            hay = " ".join(str(row.get(field) or "") for field in fields).lower()
            if needle in hay:
                chosen.append(row)
    total = len(chosen)
    try:
        page_i = int(page or 1)
    except (TypeError, ValueError):
        page_i = 1
    try:
        size = int(page_size or 25)
    except (TypeError, ValueError):
        size = 25
    page_i = max(1, page_i)
    size = min(100, max(1, size))
    start = (page_i - 1) * size
    return {"rows": chosen[start:start + size], "total": total, "page": page_i, "pageSize": size}


def validate_changes(changes: list[dict]) -> None:
    for change in changes or []:
        op = change.get("op")
        if op not in SAFE_OPS:
            raise UnsafeChange(op or "empty")
        if "rack" in change or change.get("rename"):
            raise UnsafeChange("rack")
        fields = change.get("fields") or {}
        if op == "create_device":
            if fields and set(fields) - PATCH_FIELDS:
                raise UnsafeChange("create")
            if change.get("rack") or change.get("rack_id"):
                raise UnsafeChange("rack")
        if op == "attach_vc":
            extra = set(fields) - {"virtual_chassis", "vc_position"}
            if extra:
                raise UnsafeChange("attach")
        if op == "set_custom_fields":
            if any(not str(key).startswith("eox_") for key in fields):
                raise UnsafeChange("custom")
        if op == "set_coords":
            allowed = {"op", "site_id", "latitude", "longitude", "name"}
            if set(change) - allowed:
                raise UnsafeChange("coords")
        if op == "set_primary_if_empty" and set(fields) - {"primary_ip4"}:
            raise UnsafeChange("primary")


def _short(name: str, suffixes) -> str:
    return strip_hostname(name or "", suffixes) or (name or "")


def _member_rows(modules: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for module in modules:
        kind = (module.get("class") or "").strip().lower()
        label = module.get("name") or ""
        if kind not in ("chassis", "stack") and not _SWITCH_MEMBER.match(label.strip()):
            continue
        grouped.setdefault(module.get("ip") or "", []).append(module)
    return {ip: rows for ip, rows in grouped.items() if ip and len(rows) >= 2}


def plan_stacks(devices: list[dict], modules: list[dict], netbox: list[dict], suffixes) -> dict:
    index = build_index(netbox, suffixes)
    by_ip = {host_ip(device.get("ip") or ""): device for device in devices}
    stacks = []
    changes = []
    conflicts = []
    for ip, members in sorted(_member_rows(modules).items()):
        master = by_ip.get(ip) or {"ip": ip, "name": ip, "serial": ""}
        stack_name = _short(master.get("name") or master.get("dns") or ip, suffixes) or ip
        ordered = sorted(members, key=lambda row: (int(row.get("pos") or 0) or 9999, int(row.get("index") or 0)))
        positions = []
        used = set()
        for offset, member in enumerate(ordered, start=1):
            pos = int(member.get("pos") or 0) or offset
            while pos in used:
                pos += 1
            used.add(pos)
            positions.append((pos, member))
        master_match = match_one(
            {"serial": master.get("serial") or "", "name": stack_name, "ip": ip},
            index, suffixes,
        )
        site = ""
        role = "Access switch"
        if master_match.get("device"):
            site = master_match["device"].get("site") or ""
            role = master_match["device"].get("role") or role
        planned_members = []
        pending = False
        for pos, member in positions:
            serial = member.get("serial") or ""
            raw_name = (member.get("name") or "").strip()
            if _SWITCH_MEMBER.match(raw_name) or not raw_name:
                member_name = "%s-%s" % (stack_name, pos)
            else:
                member_name = _short(raw_name, suffixes) or raw_name
            # The stack management IP belongs to the master only.
            item = {"serial": serial, "name": member_name, "ip": ip if pos == positions[0][0] else ""}
            found = match_one(item, index, suffixes, use_ip=(pos == positions[0][0]))
            action = "create"
            matched = None
            if found.get("conflict"):
                action = "conflict"
                pending = True
                conflicts.append(_conflict(
                    "stack-member",
                    "%s member %s" % (stack_name, pos),
                    "several NetBox devices match",
                    {"stack": stack_name, "position": pos, "via": found.get("via")},
                ))
            elif found.get("device"):
                matched = found["device"]
                action = "attach"
                if names_differ(member_name, matched.get("name") or "", suffixes) and norm_serial(serial):
                    conflicts.append(_conflict(
                        "name",
                        member_name,
                        matched.get("name") or "",
                        {"serial": serial, "netbox_id": matched.get("id"), "note": "existing name is kept"},
                    ))
                if matched.get("vc_id"):
                    action = "skip"
                else:
                    changes.append({
                        "op": "attach_vc",
                        "device_id": matched.get("id"),
                        "vc_name": stack_name,
                        "vc_position": pos,
                        "fields": {"virtual_chassis": stack_name, "vc_position": pos},
                    })
                    pending = True
            else:
                pending = True
                changes.append({
                    "op": "create_device",
                    "name": member_name[:64],
                    "serial": serial,
                    "model": member.get("model") or master.get("model") or "unknown",
                    "vendor": master.get("vendor") or "Cisco",
                    "site": site or "discovered",
                    "role": role or "Access switch",
                    "ip": item["ip"],
                    "vc_name": stack_name,
                    "vc_position": pos,
                })
            planned_members.append({
                "position": pos,
                "name": member_name,
                "serial": serial,
                "model": member.get("model") or "",
                "action": action,
                "via": found.get("via") or "",
                "netbox": matched.get("name") if matched else "",
                "netboxId": matched.get("id") if matched else None,
            })
        if any(member["action"] in ("create", "attach") for member in planned_members):
            changes.insert(0, {"op": "create_vc", "name": stack_name}) if not any(
                change.get("op") == "create_vc" and change.get("name") == stack_name for change in changes
            ) else None
        stacks.append({
            "id": ip,
            "name": stack_name,
            "ip": ip,
            "pending": pending,
            "members": planned_members,
        })
    # create_vc must come first. Stable, de-duplicated.
    vc_names = []
    rest = []
    for change in changes:
        if change.get("op") == "create_vc":
            if change["name"] not in vc_names:
                vc_names.append(change["name"])
        else:
            rest.append(change)
    ordered_changes = [{"op": "create_vc", "name": name} for name in vc_names] + rest
    return {"stacks": stacks, "changes": ordered_changes, "conflicts": conflicts}


def plan_addresses(addresses: list[dict], devices: list[dict], netbox: list[dict], existing_ips: dict, suffixes) -> dict:
    """existing_ips maps address -> {device_id, interface}."""
    nd_by_ip = {host_ip(device.get("ip") or ""): device for device in devices}
    index = build_index(netbox, suffixes)
    rows = []
    changes = []
    conflicts = []
    for row in addresses:
        address = host_ip(row.get("address") or "")
        if not address:
            continue
        owner = nd_by_ip.get(host_ip(row.get("device_ip") or "")) or {
            "ip": row.get("device_ip") or "",
            "name": row.get("dns") or "",
            "serial": "",
        }
        found = match_one(
            {"serial": owner.get("serial") or "", "name": owner.get("name") or owner.get("dns") or "", "ip": owner.get("ip") or ""},
            index, suffixes,
        )
        interface = (row.get("port") or "").strip() or "mgmt"
        device = found.get("device")
        action = "skip"
        note = ""
        if found.get("conflict"):
            action = "conflict"
            conflicts.append(_conflict("ip", address, "several devices", {"via": found.get("via")}))
        elif not device:
            action = "unmatched"
            note = "No NetBox device matches this Netdisco device"
        else:
            current = existing_ips.get(address)
            if current and str(current.get("device_id")) == str(device.get("id")) and (current.get("interface") or "") == interface:
                action = "present"
            elif current and str(current.get("device_id")) != str(device.get("id")):
                action = "conflict"
                conflicts.append(_conflict(
                    "ip",
                    address,
                    "assigned to %s" % (current.get("device") or current.get("device_id")),
                    {"wanted": device.get("name"), "interface": interface},
                ))
            else:
                action = "assign"
                changes.append({
                    "op": "ensure_interface",
                    "device_id": device.get("id"),
                    "name": interface,
                })
                changes.append({
                    "op": "assign_ip",
                    "device_id": device.get("id"),
                    "interface": interface,
                    "address": address + "/32",
                })
                if not device.get("primary_set"):
                    changes.append({
                        "op": "set_primary_if_empty",
                        "device_id": device.get("id"),
                        "address": address + "/32",
                        "fields": {"primary_ip4": address},
                    })
        rows.append({
            "id": "%s|%s|%s" % (owner.get("ip") or "", interface, address),
            "device": _short(owner.get("name") or owner.get("dns") or "", suffixes) or owner.get("ip") or "",
            "address": address,
            "interface": interface,
            "netbox": device.get("name") if device else "",
            "via": found.get("via") or "",
            "action": action,
            "note": note,
        })
    return {"rows": rows, "changes": changes, "conflicts": conflicts}


def plan_controllers(netdisco: list[dict], netbox: list[dict], targets: list[dict], ap_counts: dict, suffixes) -> dict:
    index = build_index(netbox, suffixes)
    rows = []
    changes = []
    seen = set()
    candidates = []
    for device in netdisco:
        blob = " ".join([device.get("model") or "", device.get("description") or "", device.get("vendor") or ""])
        role = (device.get("role") or "").lower()
        if _WLC.search(blob) or "wireless-controller" in role:
            candidates.append(device)
    for target in targets:
        candidates.append({
            "ip": target.get("ip") or "",
            "name": target.get("name") or target.get("ip") or "",
            "model": target.get("model") or "",
            "serial": target.get("serial") or "",
            "vendor": target.get("vendor") or "Cisco",
            "platform": target.get("platform") or "",
        })
    for device in netbox:
        role = (device.get("role") or "").lower()
        if "wireless" in role and "controller" in role or (device.get("role_slug") or "") == "wireless-controller":
            key = str(device.get("id"))
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "id": "nb-%s" % device.get("id"),
                "name": device.get("name") or "",
                "ip": device.get("ip") or "",
                "model": device.get("model") or "",
                "source": "netbox",
                "inNetbox": True,
                "apCount": int(ap_counts.get(device.get("name") or "", 0) or ap_counts.get(device.get("ip") or "", 0) or 0),
                "action": "present",
            })
    for device in candidates:
        ip = host_ip(device.get("ip") or "")
        name = _short(device.get("name") or device.get("dns") or ip, suffixes)
        ident = ip or name
        if not ident or ident in seen:
            continue
        found = match_one(device, index, suffixes)
        if found.get("device"):
            seen.add(ident)
            nb = found["device"]
            rows.append({
                "id": "nd-%s" % ident,
                "name": name,
                "ip": ip,
                "model": device.get("model") or "",
                "source": "netdisco",
                "inNetbox": True,
                "netbox": nb.get("name") or "",
                "apCount": int(ap_counts.get(name, 0) or ap_counts.get(ip, 0) or 0),
                "action": "present",
                "via": found.get("via") or "",
            })
            continue
        seen.add(ident)
        rows.append({
            "id": "nd-%s" % ident,
            "name": name,
            "ip": ip,
            "model": device.get("model") or "",
            "serial": device.get("serial") or "",
            "source": "netdisco",
            "inNetbox": False,
            "apCount": int(ap_counts.get(name, 0) or ap_counts.get(ip, 0) or 0),
            "action": "create",
        })
        changes.append({
            "op": "create_device",
            "name": (name or ip)[:64],
            "serial": device.get("serial") or "",
            "model": device.get("model") or "Wireless Controller",
            "vendor": device.get("vendor") or "Cisco",
            "site": "discovered",
            "role": "Wireless Controller",
            "ip": ip,
            "platform": device.get("platform") or "",
        })
    return {"rows": rows, "changes": changes}


def plan_aps(aps: list[dict], netbox: list[dict], suffixes) -> dict:
    index = build_index(netbox, suffixes)
    nb_by_name = {}
    for device in netbox:
        for form in (device.get("name") or "",):
            if form:
                nb_by_name[form.strip().lower()] = device
    rows = []
    changes = []
    for ap in aps:
        item = {"serial": ap.get("serial") or "", "name": ap.get("name") or "", "ip": ap.get("ip") or ""}
        found = match_one(item, index, suffixes)
        neighbor = _short(ap.get("neighbor") or "", suffixes)
        site = ""
        if neighbor and neighbor.lower() in nb_by_name:
            site = nb_by_name[neighbor.lower()].get("site") or ""
        action = "present" if found.get("device") else ("conflict" if found.get("conflict") else "create")
        if action == "create":
            changes.append({
                "op": "create_device",
                "name": (ap.get("name") or ap.get("ip") or "ap")[:64],
                "serial": ap.get("serial") or "",
                "model": ap.get("model") or "Access Point",
                "vendor": "Cisco",
                "site": site or "discovered",
                "role": "Access point",
                "ip": ap.get("ip") or "",
                "ap_id": ap.get("id"),
            })
        rows.append({
            "id": ap.get("id"),
            "wlc": ap.get("wlc") or "",
            "name": ap.get("name") or "",
            "model": ap.get("model") or "",
            "serial": ap.get("serial") or "",
            "ip": ap.get("ip") or "",
            "neighbor": neighbor,
            "neighborPort": ap.get("neighbor_port") or "",
            "platform": ap.get("platform") or "",
            "inNetbox": bool(found.get("device")),
            "via": found.get("via") or "",
            "action": action,
            "site": site,
        })
    return {"rows": rows, "changes": changes}


def plan_fortigates(gates: list[dict], netbox: list[dict], suffixes) -> list[dict]:
    index = build_index(netbox, suffixes)
    rows = []
    for gate in gates:
        found = match_one(
            {"serial": gate.get("serial") or "", "name": gate.get("name") or "", "ip": gate.get("ip") or ""},
            index, suffixes,
        )
        device = found.get("device")
        site_differs = False
        if device and gate.get("site") and device.get("site") and names_differ(gate.get("site") or "", device.get("site") or "", None):
            site_differs = (gate.get("site") or "").strip().lower() != (device.get("site") or "").strip().lower()
        rows.append({
            "id": gate.get("serial") or gate.get("name") or gate.get("ip"),
            "name": gate.get("name") or "",
            "serial": gate.get("serial") or "",
            "ip": gate.get("ip") or "",
            "platform": gate.get("platform") or "",
            "adom": gate.get("adom") or "",
            "inNetbox": bool(device),
            "netbox": device.get("name") if device else "",
            "via": found.get("via") or "",
            "siteDiffers": site_differs,
        })
    return rows


def round_coord(value) -> float:
    return round(float(value), 6)


def accept_geocode(site: dict, hit: dict) -> bool:
    if not hit or hit.get("lat") in (None, "") or hit.get("lon") in (None, ""):
        return False
    country = (site.get("country") or "").strip().lower()
    code = (site.get("country_code") or "").strip().lower()
    found_country = (hit.get("country") or "").strip().lower()
    found_code = (hit.get("country_code") or "").strip().lower()
    if code and found_code and code != found_code:
        return False
    if country and found_country and country not in found_country and found_country not in country:
        return False
    region = (site.get("region") or "").strip().lower()
    label = (hit.get("label") or "").lower()
    name = (site.get("name") or "").strip().lower()
    if region and region not in label and name not in label:
        return False
    if name and name not in label and region and region not in label:
        return False
    return True


def plan_sites(sites: list[dict], hits: dict[str, dict]) -> dict:
    rows = []
    changes = []
    for site in sites:
        lat = site.get("latitude")
        lon = site.get("longitude")
        if lat not in (None, "") and lon not in (None, ""):
            continue
        hit = hits.get(str(site.get("id")))
        if not accept_geocode(site, hit or {}):
            rows.append({
                "id": site.get("id"),
                "name": site.get("name") or "",
                "region": site.get("region") or "",
                "country": site.get("country") or "",
                "action": "unresolved",
                "note": "No geocode result inside this site's region or country",
            })
            continue
        latitude = round_coord(hit["lat"])
        longitude = round_coord(hit["lon"])
        rows.append({
            "id": site.get("id"),
            "name": site.get("name") or "",
            "region": site.get("region") or "",
            "country": site.get("country") or "",
            "latitude": latitude,
            "longitude": longitude,
            "label": hit.get("label") or "",
            "action": "set",
        })
        changes.append({
            "op": "set_coords",
            "site_id": site.get("id"),
            "name": site.get("name") or "",
            "latitude": latitude,
            "longitude": longitude,
        })
    return {"rows": rows, "changes": changes}


def geocode_query(site: dict) -> str:
    parts = [site.get("name") or "", site.get("address") or "", site.get("region") or "", site.get("country") or ""]
    return ", ".join(part.strip() for part in parts if part and str(part).strip())


def eox_bucket(last_support: str, today: date | None = None) -> str:
    text = (last_support or "").strip()
    if not text:
        return "unknown"
    try:
        stamp = datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return "unknown"
    current = today or date.today()
    if stamp < current:
        return "past"
    if stamp < current + timedelta(days=365):
        return "soon"
    return "ok"


def cisco_device(device: dict) -> bool:
    blob = " ".join([
        device.get("manufacturer") or "",
        device.get("vendor") or "",
        device.get("platform") or "",
    ]).lower()
    return "cisco" in blob


def eox_pid(device: dict) -> str:
    for field in ("part", "model"):
        text = (device.get(field) or "").strip()
        if text and text.lower() != "unknown":
            return text
    return ""


def plan_eox_writes(rows: list[dict]) -> list[dict]:
    changes = [{"op": "ensure_custom_field", "name": name} for name in EOX_FIELDS]
    for row in rows:
        if not row.get("netbox_id"):
            continue
        fields = {
            "eox_end_of_sale": row.get("end_of_sale") or "",
            "eox_end_of_sw_maintenance": row.get("end_of_sw_maintenance") or "",
            "eox_end_of_security": row.get("end_of_security") or "",
            "eox_last_date_of_support": row.get("last_date_of_support") or "",
            "eox_migration_pid": row.get("migration_pid") or "",
        }
        if not any(fields.values()):
            continue
        changes.append({
            "op": "set_custom_fields",
            "device_id": row.get("netbox_id"),
            "name": row.get("name") or "",
            "fields": fields,
        })
    return changes


def detect_conflicts(netdisco: list[dict], netbox: list[dict], suffixes) -> list[dict]:
    index = build_index(netbox, suffixes)
    found = []
    for device in netdisco:
        result = match_one(device, index, suffixes)
        nb = result.get("device")
        if not nb:
            continue
        serial = norm_serial(device.get("serial") or "")
        left_name = _short(device.get("name") or device.get("dns") or "", suffixes)
        if serial and names_differ(left_name, nb.get("name") or "", suffixes):
            found.append(_conflict("name", left_name, nb.get("name") or "", {
                "serial": device.get("serial") or "",
                "netbox_id": nb.get("id"),
                "note": "names differ; NetBox name is kept",
            }))
        left_ip = host_ip(device.get("ip") or "")
        right_ip = host_ip(nb.get("ip") or "")
        if serial and left_ip and right_ip and left_ip != right_ip and result.get("via") == "serial":
            found.append(_conflict("ip", left_ip, right_ip, {
                "serial": device.get("serial") or "",
                "name": left_name,
                "netbox_id": nb.get("id"),
            }))
        nb_serial = norm_serial(nb.get("serial") or "")
        if nb_serial and serial and nb_serial != serial and result.get("via") == "hostname":
            found.append(_conflict("serial", device.get("serial") or "", nb.get("serial") or "", {
                "name": left_name,
                "netbox_id": nb.get("id"),
            }))
        location = (device.get("location") or "").strip()
        site = (nb.get("site") or "").strip()
        if location and site and location.lower() != site.lower():
            found.append(_conflict("site", location, site, {
                "name": left_name or device.get("ip") or "",
                "netbox_id": nb.get("id"),
                "note": "site is not overwritten",
            }))
    return found


def _conflict(kind: str, left: str, right: str, detail: dict) -> dict:
    fingerprint = "%s|%s|%s" % (kind, (left or "").strip().lower(), (right or "").strip().lower())
    return {
        "fingerprint": fingerprint[:200],
        "kind": kind,
        "left": left,
        "right": right,
        "detail": detail,
    }


def is_wlc(device: dict) -> bool:
    blob = " ".join([
        device.get("model") or "",
        device.get("description") or "",
        device.get("role") or "",
        device.get("role_slug") or "",
    ])
    return bool(_WLC.search(blob) or (device.get("role_slug") or "") == "wireless-controller")
