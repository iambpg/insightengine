"""Parent/child tree from the Claremont CDP shape. No network and no NetBox."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from ie_config.hierarchy import (
    NetBoxHierarchyWriter,
    apply_changes,
    approved_rows,
    build_hierarchy,
    is_subnet_root,
    metrics_text,
    proposal_items,
    read_auto_apply,
    scrape_file,
    write_auto_apply,
    write_scrape_file,
)

ROOT = Path(__file__).resolve().parents[2]


def device(ident, hostname, role, ip, form="access-switch-48", **extra):
    row = {
        "id": str(ident),
        "hostname": hostname,
        "role": role,
        "mgmtIp": ip.split("/")[0],
        "prefix": ip,
        "formFactor": form,
    }
    row.update(extra)
    return row


def link(local, local_port, remote, remote_port):
    return {
        "local": local,
        "localPort": local_port,
        "remoteName": remote,
        "remotePort": remote_port,
        "source": "cdp",
    }


def claremont():
    devices = [
        device(1, "wc18.cc30-claremont-1rsw01", "core-switches", "10.129.32.1/32", "switch-stack"),
        device(2, "wc18-claremont-0asw01", "access-switches", "10.129.32.17/32"),
        device(3, "wc18-claremont-0asw02", "access-switches", "10.129.32.18/32"),
        device(4, "wc18-claremont-0asp01", "access-switches", "10.129.32.16/32", "access-switch-24"),
        device(5, "wc18-claremont-wc-cpt", "sdwan", "10.129.32.2/32", "firewall"),
        device(8, "OiOB-Bree-WLC01", "wireless-controller", "10.96.6.2/32", "modular-chassis"),
        device(9, "AP-WC18", "access-point", "10.129.32.50/32", "ceiling-ap", wlc="OiOB-Bree-WLC01"),
        device(10, "wc18-orphan-asw", "access-switches", "10.129.40.10/32"),
        device(11, "SEP488B0ABCBAB1", "access-switches", "10.129.32.60/32"),
    ]
    links = [
        # 9200 has two uplinks to the 3560. Gi1/0/23 is the lower interface.
        link("wc18-claremont-0asw01", "Gi1/0/24", "wc18.cc30-claremont-1rsw01", "Gi0/4"),
        link("wc18-claremont-0asw01", "Gi1/0/23", "wc18.cc30-claremont-1rsw01", "Gi0/5"),
        # The same link seen from the core must not become a second choice.
        link("wc18.cc30-claremont-1rsw01", "Gi0/5", "wc18-claremont-0asw01", "Gi1/0/23"),
        link("wc18-claremont-0asw02", "Gi1/0/1", "wc18.cc30-claremont-1rsw01", "Gi0/6"),
    # 2960 is two hops from the core through either 9200. Fa0/23 is the lower port.
    link("wc18-claremont-0asp01", "Fa0/24", "wc18-claremont-0asw01", "Gi1/0/48"),
    link("wc18-claremont-0asp01", "Fa0/23", "wc18-claremont-0asw02", "Gi1/0/48"),
        # A phone on Fa0/1 and an unknown camera are not devices in the tree.
        link("wc18-claremont-0asp01", "Fa0/1", "SEP488B0ABCBAB1", "Port 1"),
        link("wc18-claremont-0asp01", "Fa0/2", "camera-till", "eth0"),
        link("wc18-claremont-wc-cpt", "lan", "wc18.cc30-claremont-1rsw01", "Gi0/1"),
        # AP CDP from the controller names the access switch, not the WLC.
        link("AP-WC18", "uplink", "wc18-claremont-0asw01", "Gi1/0/10"),
        link("AP-WC18", "capwap", "OiOB-Bree-WLC01", "Te0/0/0"),
    ]
    return devices, links


def by_name(report):
    return {node["hostname"]: node for node in report["nodes"]}


def test_host_route_dot_one_is_the_root():
    assert is_subnet_root("10.129.32.1/32") is True
    assert is_subnet_root("10.129.32.1") is True
    assert is_subnet_root("10.129.32.17/24") is False
    assert is_subnet_root("10.129.32.1/24") is True
    assert is_subnet_root("10.129.32.2/32") is False


def test_claremont_tree_picks_the_shorter_path_then_the_lower_interface():
    devices, links = claremont()
    report = build_hierarchy(devices, links)
    nodes = by_name(report)

    root = nodes["wc18.cc30-claremont-1rsw01"]
    assert root["root"] is True
    assert root["parentHostname"] == ""
    assert root["flagged"] is False

    first = nodes["wc18-claremont-0asw01"]
    assert first["parentHostname"] == "wc18.cc30-claremont-1rsw01"
    assert first["uplinkInterface"] == "Gi1/0/23"
    assert first["parentInterface"] == "Gi0/5"
    assert first["hops"] == 1

    second = nodes["wc18-claremont-0asw02"]
    assert second["parentHostname"] == "wc18.cc30-claremont-1rsw01"
    assert second["uplinkInterface"] == "Gi1/0/1"

    access = nodes["wc18-claremont-0asp01"]
    assert access["parentHostname"] == "wc18-claremont-0asw02"
    assert access["uplinkInterface"] == "Fa0/23"
    assert access["parentInterface"] == "Gi1/0/48"
    assert access["hops"] == 2

    sdwan = nodes["wc18-claremont-wc-cpt"]
    assert sdwan["root"] is False
    assert sdwan["parentHostname"] == "wc18.cc30-claremont-1rsw01"
    assert sdwan["uplinkInterface"] == "lan"
    assert sdwan["parentInterface"] == "Gi0/1"

    assert "SEP488B0ABCBAB1" not in nodes
    assert "camera-till" not in nodes
    assert "OiOB-Bree-WLC01" not in nodes

    ap = nodes["AP-WC18"]
    assert ap["parentHostname"] == "wc18-claremont-0asw01"
    assert ap["parentInterface"] == "Gi1/0/10"
    assert ap["uplinkInterface"] == "uplink"
    assert ap["wlc"] == "OiOB-Bree-WLC01"

    orphan = nodes["wc18-orphan-asw"]
    assert orphan["parentHostname"] == ""
    assert orphan["flagged"] is True
    assert orphan["reason"] == "No path to a subnet root."
    assert "10" in report["flagged"]

    child_names = [row["hostname"] for row in root["children"]]
    assert "wc18-claremont-0asw01" in child_names
    assert "wc18-claremont-wc-cpt" in child_names
    assert "AP-WC18" not in child_names


def test_shortest_path_beats_a_lower_interface():
    devices, links = claremont()
    links.append(link("wc18-claremont-0asp01", "Fa0/48", "wc18.cc30-claremont-1rsw01", "Gi0/8"))
    access = by_name(build_hierarchy(devices, links))["wc18-claremont-0asp01"]
    assert access["hops"] == 1
    assert access["parentHostname"] == "wc18.cc30-claremont-1rsw01"
    assert access["uplinkInterface"] == "Fa0/48"


def test_a_down_parent_marks_the_child():
    devices, links = claremont()
    devices[0]["probeDown"] = True
    nodes = by_name(build_hierarchy(devices, links))
    assert nodes["wc18-claremont-0asw01"]["parentDown"] is True
    assert nodes["wc18-claremont-0asp01"]["parentDown"] is False


def test_approved_parent_differs_until_it_matches_the_proposal():
    devices, links = claremont()
    devices[1]["approvedParentId"] = "1"
    devices[1]["approvedParentName"] = "wc18.cc30-claremont-1rsw01"
    devices[1]["approvedParentInterface"] = "Gi0/4"
    devices[1]["approvedUplink"] = "Gi1/0/24"
    nodes = by_name(build_hierarchy(devices, links))
    assert nodes["wc18-claremont-0asw01"]["differs"] is True
    devices[1]["approvedParentInterface"] = "Gi0/5"
    devices[1]["approvedUplink"] = "Gi1/0/23"
    nodes = by_name(build_hierarchy(devices, links))
    assert nodes["wc18-claremont-0asw01"]["differs"] is False


def test_file_sd_omits_an_empty_parent_and_keeps_a_root_that_has_children():
    devices, links = claremont()
    devices[1]["approvedParentId"] = "1"
    devices[1]["approvedParentName"] = "wc18.cc30-claremont-1rsw01"
    devices[1]["approvedParentInterface"] = "Gi0/5"
    devices[1]["approvedUplink"] = "Gi1/0/23"
    devices[3]["approvedParentId"] = "3"
    devices[3]["approvedParentName"] = "wc18-claremont-0asw02"
    devices[3]["approvedParentInterface"] = "Gi1/0/48"
    devices[3]["approvedUplink"] = "Fa0/24"
    rows = {row["hostname"]: row for row in approved_rows(build_hierarchy(devices, links)["nodes"])}
    assert rows["wc18.cc30-claremont-1rsw01"]["topology_parent"] == "yes"
    assert "parent" not in rows["wc18.cc30-claremont-1rsw01"]
    assert rows["wc18-claremont-0asw01"]["parent"] == "wc18.cc30-claremont-1rsw01"
    assert rows["wc18-claremont-0asw01"]["topology_parent"] == "no"
    assert rows["wc18-claremont-0asw02"]["topology_parent"] == "yes"
    assert "parent" not in rows["wc18-claremont-0asw02"]
    assert rows["wc18-claremont-0asp01"]["parent"] == "wc18-claremont-0asw02"
    assert rows["wc18-claremont-0asp01"]["topology_parent"] == "no"
    assert "wc18-orphan-asw" not in rows
    text = metrics_text(build_hierarchy(devices, links)["nodes"])
    assert 'hostname="wc18-claremont-0asp01"' in text
    assert 'parent=""' not in text
    assert scrape_file()[0]["targets"] == ["ie-config:8080"]


def test_apply_writes_the_override_and_audits_a_failure():
    devices, links = claremont()
    nodes = build_hierarchy(devices, links)["nodes"]
    calls = []

    def request(method, path, body=None):
        calls.append((method, path, body))
        if method == "GET":
            return {"results": []}
        if method == "PATCH" and path.endswith("/3/"):
            raise RuntimeError("netbox refused")
        return {"ok": True}

    writer = NetBoxHierarchyWriter(request)
    results = apply_changes(writer, nodes, [
        {"id": "2"},
        {"id": "3", "parentId": "1", "parentInterface": "Gi0/6", "uplinkInterface": "Fa0/22"},
        {"id": "99"},
    ])
    by_id = {row["id"]: row for row in results}
    assert by_id["2"]["ok"] is True
    assert by_id["2"]["parentHostname"] == "wc18.cc30-claremont-1rsw01"
    assert by_id["2"]["uplinkInterface"] == "Gi1/0/23"
    assert by_id["3"]["ok"] is False
    assert "refused" in by_id["3"]["error"]
    assert by_id["99"]["ok"] is False
    posted = [call for call in calls if call[0] == "POST"]
    assert {call[1] for call in posted} == {"/api/extras/custom-fields/"}
    assert {call[2]["name"] for call in posted} == {"parent_device", "parent_interface", "uplink_interface"}
    parent_spec = next(call[2] for call in posted if call[2]["name"] == "parent_device")
    assert parent_spec["type"] == "object"
    assert parent_spec["related_object_type"] == "dcim.device"
    patched = next(call for call in calls if call[0] == "PATCH" and call[1].endswith("/2/"))
    assert patched[2]["custom_fields"]["parent_device"] == 1
    assert patched[2]["custom_fields"]["uplink_interface"] == "Gi1/0/23"


def test_auto_apply_defaults_off_and_proposals_skip_an_agreed_parent(tmp_path):
    path = tmp_path / "hierarchy-settings.json"
    assert read_auto_apply(str(path)) is False
    write_auto_apply(str(path), False)
    assert json.loads(path.read_text()) == {"autoApply": False}
    devices, links = claremont()
    devices[1]["approvedParentId"] = "1"
    devices[1]["approvedParentName"] = "wc18.cc30-claremont-1rsw01"
    devices[1]["approvedParentInterface"] = "Gi0/5"
    devices[1]["approvedUplink"] = "Gi1/0/23"
    pending = {item["id"] for item in proposal_items(build_hierarchy(devices, links)["nodes"])}
    assert "2" not in pending
    assert "4" in pending


def test_scrape_file_is_a_single_ie_config_target(tmp_path):
    path = tmp_path / "topology.yml"
    write_scrape_file(str(path))
    loaded = yaml.safe_load(path.read_text())
    assert loaded == scrape_file()


def test_alert_rules_inhibit_children_when_the_parent_is_down():
    rules = yaml.safe_load((ROOT / "config/prometheus/alert-rules.yml").read_text())
    groups = {group["name"]: group for group in rules["groups"]}
    alerts = {alert["alert"]: alert for alert in groups["insightengine-collectors"]["rules"]}
    unreachable = alerts["DeviceUnreachable"]["expr"]
    assert "ie_topology_info" in unreachable
    assert 'parent!=""' in unreachable
    parent_down = alerts["TopologyParentDown"]
    assert 'topology_parent="yes"' in parent_down["expr"]
    assert parent_down["labels"]["parent"] == "{{ $labels.hostname }}"
    manager = yaml.safe_load((ROOT / "config/alertmanager/alertmanager.yml").read_text())
    inhibit = manager["inhibit_rules"]
    assert any(
        rule.get("equal") == ["parent"]
        and 'alertname="TopologyParentDown"' in rule.get("source_matchers", [])
        and 'alertname="DeviceUnreachable"' in rule.get("target_matchers", [])
        for rule in inhibit
    )
    assert any(route.get("receiver") == "blackhole" for route in manager["route"]["routes"])
    assert any(receiver.get("name") == "blackhole" for receiver in manager["receivers"])
