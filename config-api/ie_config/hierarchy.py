"""Parent/child tree from CDP and LLDP.

Only NetBox devices we monitor are nodes: core, distribution and access
switches, SD-WAN, firewalls, routers, and access points. Phones and any
neighbour that is not one of those devices are ignored.

The root of a subnet is the device whose management address is the .1 of
that prefix. The tree is a breadth-first walk from those roots. A device's
parent is the neighbour one hop closer to the root. Two uplinks keep the
shorter path, then the lower interface name. A device with no path is left
without a parent and flagged.

An access point's parent is the switch in its controller CDP neighbour.
The wireless controller is recorded beside the AP and is not the parent.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
from collections import deque

import yaml

from .ifnames import canonical_iface

MONITORED_ROLES = {
    "core-switch",
    "core-switches",
    "distribution-switch",
    "distribution-switches",
    "access-switch",
    "access-switches",
    "sdwan",
    "sd-wan",
    "firewall",
    "core-firewall",
    "hub",
    "router",
    "branch-router",
    "access-point",
    "ap",
}

MONITORED_FORMS = {
    "access-switch-24",
    "access-switch-48",
    "switch-stack",
    "firewall",
    "branch-router",
    "ceiling-ap",
}

_PHONE = re.compile(r"^(sep[0-9a-f]{6,}|(?:ip[- ]?)?phone|polycom|ata)\b", re.IGNORECASE)
_NUM = re.compile(r"(\d+)")


def is_phone(name: str) -> bool:
    return bool(_PHONE.match((name or "").strip()))


def is_monitored(device: dict) -> bool:
    role = str(device.get("role") or device.get("role_slug") or "").strip().lower()
    form = str(device.get("formFactor") or device.get("form_factor") or "").strip().lower()
    if role in ("wireless-controller", "wlc"):
        return False
    if is_phone(str(device.get("hostname") or device.get("name") or "")):
        return False
    if role in MONITORED_ROLES or form in MONITORED_FORMS:
        return True
    return False


def is_subnet_root(address: str) -> bool:
    """True when this management address is the .1 of its prefix.

    A host route (/32 or a bare address) uses the last octet, so 10.129.32.1
    is the root. A wider prefix uses the first host of that network.
    """
    text = (address or "").strip()
    if not text or text == "—":
        return False
    try:
        if "/" in text:
            iface = ipaddress.ip_interface(text)
            host = iface.ip
            network = iface.network
            if not isinstance(host, ipaddress.IPv4Address):
                return False
            if network.prefixlen >= 31:
                return int(host) & 0xFF == 1
            return host == network.network_address + 1
        host = ipaddress.ip_address(text)
    except ValueError:
        return False
    return isinstance(host, ipaddress.IPv4Address) and int(host) & 0xFF == 1


def iface_sort_key(name: str) -> tuple:
    canon = canonical_iface(name or "")
    pieces = _NUM.split(canon)
    key = []
    for piece in pieces:
        if piece.isdigit():
            key.append((0, int(piece)))
        else:
            key.append((1, piece))
    return tuple(key)


def _device_id(device: dict) -> str:
    return str(device.get("id") or "")


def _hostname(device: dict) -> str:
    return str(device.get("hostname") or device.get("name") or "")


def build_hierarchy(devices: list[dict], links: list[dict]) -> dict:
    """Return the proposed tree. `links` use local/remote names or ids and both ports."""
    eligible = []
    for device in devices or []:
        if not isinstance(device, dict) or not is_monitored(device):
            continue
        if not _device_id(device) or not _hostname(device):
            continue
        eligible.append(device)
    by_id = {_device_id(device): device for device in eligible}
    by_name: dict[str, dict] = {}
    by_ip: dict[str, dict] = {}
    for device in eligible:
        by_name.setdefault(_hostname(device).lower(), device)
        ip = str(device.get("mgmtIp") or device.get("ip") or "").split("/")[0].strip()
        if ip and ip != "—":
            by_ip.setdefault(ip, device)

    def resolve(name: str = "", ip: str = "", ident: str = "") -> dict | None:
        if ident and ident in by_id:
            return by_id[ident]
        text = (name or "").strip()
        if text and text.lower() in by_name:
            return by_name[text.lower()]
        host = text.split(".")[0].lower()
        if host and host in by_name:
            return by_name[host]
        addr = (ip or "").split("/")[0].strip()
        if addr and addr in by_ip:
            return by_ip[addr]
        return None

    # Undirected edges. The same CDP/LLDP link seen from both ends is one edge.
    edges: dict[str, list[dict]] = {ident: [] for ident in by_id}
    seen = set()
    for link in links or []:
        if not isinstance(link, dict):
            continue
        left = resolve(str(link.get("local") or link.get("localName") or ""), str(link.get("localAddress") or ""), str(link.get("localId") or ""))
        right = resolve(str(link.get("remoteName") or link.get("remote") or ""), str(link.get("remoteAddress") or ""), str(link.get("remoteId") or ""))
        if left is None or right is None or _device_id(left) == _device_id(right):
            continue
        left_port = str(link.get("localPort") or "")
        right_port = str(link.get("remotePort") or "")
        pair = tuple(sorted((
            (_device_id(left), canonical_iface(left_port)),
            (_device_id(right), canonical_iface(right_port)),
        )))
        if pair in seen:
            continue
        seen.add(pair)
        edges[_device_id(left)].append({"peer": _device_id(right), "mine": left_port, "theirs": right_port})
        edges[_device_id(right)].append({"peer": _device_id(left), "mine": right_port, "theirs": left_port})

    roots = [ident for ident, device in by_id.items() if is_subnet_root(str(device.get("prefix") or device.get("mgmtIp") or device.get("ip") or ""))]
    distance: dict[str, int] = {ident: 0 for ident in roots}
    queue: deque[str] = deque(roots)
    while queue:
        current = queue.popleft()
        for edge in edges.get(current) or []:
            peer = edge["peer"]
            if peer in distance:
                continue
            distance[peer] = distance[current] + 1
            queue.append(peer)

    chosen: dict[str, dict] = {}
    for ident, hops in distance.items():
        if hops == 0:
            continue
        best = None
        best_key = None
        for edge in edges.get(ident) or []:
            peer = edge["peer"]
            if distance.get(peer) != hops - 1:
                continue
            key = (iface_sort_key(edge["mine"]), iface_sort_key(edge["theirs"]), by_id[peer]["hostname"].lower())
            if best_key is None or key < best_key:
                best_key = key
                best = edge
        if best is not None:
            chosen[ident] = best

    children: dict[str, list[dict]] = {ident: [] for ident in by_id}
    nodes = []
    for ident, device in by_id.items():
        edge = chosen.get(ident)
        parent = by_id.get(edge["peer"]) if edge else None
        hops = distance.get(ident)
        flagged = ident not in distance
        parent_down = bool(parent) and bool(parent.get("probeDown"))
        node = {
            "id": ident,
            "hostname": _hostname(device),
            "role": str(device.get("role") or device.get("role_slug") or ""),
            "mgmtIp": str(device.get("mgmtIp") or device.get("ip") or ""),
            "formFactor": str(device.get("formFactor") or device.get("form_factor") or "generic"),
            "root": ident in distance and distance[ident] == 0,
            "parentId": _device_id(parent) if parent else "",
            "parentHostname": _hostname(parent) if parent else "",
            "parentInterface": edge["theirs"] if edge else "",
            "uplinkInterface": edge["mine"] if edge else "",
            "hops": hops,
            "flagged": flagged,
            "reason": "No path to a subnet root." if flagged else "",
            "wlc": str(device.get("wlc") or ""),
            "parentDown": parent_down,
            "approvedParentId": str(device.get("approvedParentId") or ""),
            "approvedParentHostname": str(device.get("approvedParentName") or ""),
            "approvedParentInterface": str(device.get("approvedParentInterface") or ""),
            "approvedUplink": str(device.get("approvedUplink") or ""),
            "children": [],
        }
        proposed = (node["parentId"], node["parentInterface"], node["uplinkInterface"])
        approved = (node["approvedParentId"], node["approvedParentInterface"], node["approvedUplink"])
        node["differs"] = proposed != approved and not (node["root"] and not node["approvedParentId"])
        if parent:
            children[_device_id(parent)].append({
                "id": ident,
                "hostname": node["hostname"],
                "parentInterface": node["parentInterface"],
                "uplinkInterface": node["uplinkInterface"],
                "formFactor": node["formFactor"],
                "parentDown": parent_down,
            })
        nodes.append(node)
    for node in nodes:
        node["children"] = sorted(children.get(node["id"]) or [], key=lambda row: row["hostname"].lower())
        if node["root"]:
            node["differs"] = bool(node["approvedParentId"])
    nodes.sort(key=lambda row: (row["hostname"].lower()))
    return {
        "autoApply": False,
        "roots": [node["id"] for node in nodes if node["root"]],
        "flagged": [node["id"] for node in nodes if node["flagged"]],
        "nodes": nodes,
    }


def approved_rows(nodes: list[dict]) -> list[dict]:
    """One row per device that has an approved parent, or is itself a parent.

    The parent label is omitted when NetBox has no parent. An empty parent
    label would make an inhibit rule match every unparented device to every
    other one. A root that other devices point at is still included, with
    topology_parent=yes and no parent label, so its down alert can inhibit
    its children.
    """
    parents = {str(node.get("approvedParentId") or "") for node in nodes or [] if node.get("approvedParentId")}
    rows = []
    for node in nodes or []:
        parent = str(node.get("approvedParentHostname") or "").strip()
        is_parent = str(node.get("id") or "") in parents
        if not parent and not is_parent:
            continue
        labels = {
            "hostname": str(node.get("hostname") or ""),
            "topology_parent": "yes" if is_parent else "no",
        }
        if parent:
            labels["parent"] = parent
        rows.append(labels)
    rows.sort(key=lambda row: row["hostname"].lower())
    return rows


def scrape_file() -> list[dict]:
    """file_sd that makes Prometheus scrape the topology metric once.

    The parent label is on ie_topology_info, which is built from the approved
    NetBox fields. Device addresses are not scraped again.
    """
    return [{"targets": ["ie-config:8080"], "labels": {"source": "netbox-topology"}}]


def metrics_text(nodes: list[dict]) -> str:
    """Text exposition of the approved parents Prometheus scrapes via file_sd."""
    lines = [
        "# HELP ie_topology_info Approved NetBox parent of a monitored device.",
        "# TYPE ie_topology_info gauge",
    ]
    for labels in approved_rows(nodes):
        body = ",".join('%s="%s"' % (key, _escape(labels[key])) for key in ("hostname", "parent", "topology_parent") if key in labels)
        lines.append("ie_topology_info{%s} 1" % body)
    return "\n".join(lines) + "\n"


def _escape(value: str) -> str:
    return str(value or "").replace("\\", "\\\\").replace("\n", "").replace('"', '\\"')


FIELD_SPECS = (
    {
        "name": "parent_device",
        "label": "Parent device",
        "type": "object",
        "object_types": ["dcim.device"],
        "related_object_type": "dcim.device",
        "required": False,
        "description": "Uplink parent from CDP or LLDP, one hop closer to the subnet root.",
    },
    {
        "name": "parent_interface",
        "label": "Parent interface",
        "type": "text",
        "object_types": ["dcim.device"],
        "required": False,
        "description": "Interface on the parent that this device is connected to.",
    },
    {
        "name": "uplink_interface",
        "label": "Uplink interface",
        "type": "text",
        "object_types": ["dcim.device"],
        "required": False,
        "description": "Interface on this device that faces the parent.",
    },
)


def read_auto_apply(path: str) -> bool:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return False
    return bool(data.get("autoApply")) if isinstance(data, dict) else False


def write_auto_apply(path: str, enabled: bool) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump({"autoApply": bool(enabled)}, handle)
        handle.write("\n")
    os.replace(temporary, path)


def write_scrape_file(path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        yaml.safe_dump(scrape_file(), handle, sort_keys=False)
    os.replace(temporary, path)


def approved_from_custom(custom: dict, names_by_id: dict[str, str] | None = None) -> dict:
    raw = custom if isinstance(custom, dict) else {}
    parent = raw.get("parent_device")
    parent_id = ""
    parent_name = ""
    if isinstance(parent, dict):
        parent_id = str(parent.get("id") or "")
        parent_name = str(parent.get("name") or parent.get("display") or "")
    elif isinstance(parent, int) or (isinstance(parent, str) and str(parent).isdigit()):
        parent_id = str(parent)
    if parent_id and not parent_name and names_by_id:
        parent_name = names_by_id.get(parent_id, "")
    return {
        "approvedParentId": parent_id,
        "approvedParentName": parent_name,
        "approvedParentInterface": str(raw.get("parent_interface") or ""),
        "approvedUplink": str(raw.get("uplink_interface") or ""),
    }


class NetBoxHierarchyWriter:
    """Creates the three custom fields when they are missing, then patches one device.

    `request(method, path, body)` returns the decoded JSON object. This class
    does not decide *when* to write. Callers write only after approval, or when
    auto-apply is on.
    """

    def __init__(self, request):
        self._request = request

    def ensure_fields(self) -> list[str]:
        created = []
        for spec in FIELD_SPECS:
            found = self._request("GET", "/api/extras/custom-fields/?name=%s" % spec["name"]) or {}
            rows = found.get("results") or []
            if any(str(row.get("name") or "") == spec["name"] for row in rows if isinstance(row, dict)):
                continue
            self._request("POST", "/api/extras/custom-fields/", dict(spec))
            created.append(spec["name"])
        return created

    def write(self, device_id: str, parent_id: str, parent_interface: str, uplink_interface: str) -> dict:
        payload = {
            "custom_fields": {
                "parent_device": int(parent_id) if parent_id else None,
                "parent_interface": parent_interface or "",
                "uplink_interface": uplink_interface or "",
            }
        }
        return self._request("PATCH", "/api/dcim/devices/%s/" % device_id, payload) or {}


def apply_changes(writer: NetBoxHierarchyWriter, nodes: list[dict], items: list[dict]) -> list[dict]:
    """Write the chosen parent onto each child. Unknown devices are recorded, not raised."""
    by_id = {str(node.get("id") or ""): node for node in nodes or []}
    writer.ensure_fields()
    results = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        ident = str(item.get("id") or "")
        node = by_id.get(ident)
        if node is None:
            results.append({"id": ident, "ok": False, "error": "unknown device"})
            continue
        if "parentId" in item:
            parent_id = str(item.get("parentId") or "")
        else:
            parent_id = str(node.get("parentId") or "")
        parent_interface = str(item.get("parentInterface") if "parentInterface" in item else node.get("parentInterface") or "")
        uplink = str(item.get("uplinkInterface") if "uplinkInterface" in item else node.get("uplinkInterface") or "")
        if parent_id and parent_id not in by_id:
            results.append({"id": ident, "hostname": node.get("hostname") or "", "ok": False, "error": "parent is not a monitored device"})
            continue
        if parent_id == ident:
            results.append({"id": ident, "hostname": node.get("hostname") or "", "ok": False, "error": "a device cannot be its own parent"})
            continue
        parent = by_id.get(parent_id) if parent_id else None
        try:
            writer.write(ident, parent_id, parent_interface, uplink)
        except Exception as exc:
            results.append({
                "id": ident,
                "hostname": node.get("hostname") or "",
                "ok": False,
                "error": str(exc),
                "parentId": parent_id,
                "parentHostname": (parent or {}).get("hostname") or "",
                "parentInterface": parent_interface,
                "uplinkInterface": uplink,
            })
            continue
        results.append({
            "id": ident,
            "hostname": node.get("hostname") or "",
            "ok": True,
            "parentId": parent_id,
            "parentHostname": (parent or {}).get("hostname") or "",
            "parentInterface": parent_interface,
            "uplinkInterface": uplink,
        })
    return results


def proposal_items(nodes: list[dict]) -> list[dict]:
    """Every child whose proposal is not what NetBox already stores."""
    items = []
    for node in nodes or []:
        if node.get("root") and not node.get("approvedParentId"):
            continue
        if not node.get("differs"):
            continue
        items.append({
            "id": node["id"],
            "parentId": node.get("parentId") or "",
            "parentInterface": node.get("parentInterface") or "",
            "uplinkInterface": node.get("uplinkInterface") or "",
        })
    return items
