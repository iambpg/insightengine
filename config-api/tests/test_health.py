"""Health profile, panel text, AP paging, and SNMP module choice."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "config-api"))

from ie_config.health import (  # noqa: E402
    NOT_SUPPORTED,
    aireos_psu_states,
    build_health_panel,
    classify_health,
    classify_profile,
    explain_health,
    match_access_point,
    page_rows,
    suggest_ap_site,
)


def _sd():
    path = ROOT / "netbox" / "netbox_lists" / "sd.py"
    spec = importlib.util.spec_from_file_location("netbox_lists_sd_health", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_profiles_cover_the_supported_device_types():
    assert classify_profile("access-switch", "ios", "Cisco", "WS-C2960X-48FPS-L") == "ios-basic"
    assert classify_profile("core-switch", "ios", "Cisco", "WS-C3560CG-8TC-S") == "ios-basic"
    assert classify_profile("access-switch", "ios", "Cisco", "C1000-24P-4G-L") == "ios-basic"
    assert classify_profile("access-switch", "", "Cisco", "SG350-28") == "ios-basic"
    assert classify_profile("access-switch", "", "Cisco", "SG500-52") == "ios-basic"
    assert classify_profile("access-switch", "ios-xe", "Cisco", "C9300-48P") == "iosxe"
    assert classify_profile("core-switch", "nx-os", "Cisco", "N9K-C93180") == "nxos"
    assert classify_profile("wireless-controller", "aireos", "Cisco", "AIR-CT8540") == "aireos"
    assert classify_profile("wireless-controller", "ios-xe", "Cisco", "C9800-80") == "iosxe-wlc"
    assert classify_profile("access-point", "ios-xe", "Cisco", "C9120AXI") == "ap"
    assert classify_profile("sdwan", "fortigate", "Fortinet", "FG-60F") == "fortigate"
    assert classify_profile("core-firewall", "pan-os", "Palo Alto", "PA-820") == "paloalto"


def test_access_point_panel_says_not_supported():
    panel = build_health_panel("ap", ap={"status": "up", "clients": 4, "uptimeSeconds": 10, "radios": []})
    assert all(group["value"] == NOT_SUPPORTED for group in panel["groups"])
    assert panel["interfacesSupported"] is False
    assert panel["accessPoint"]["status"] == "up"
    assert "Telegraf" in panel["accessPoint"]["note"]


def test_compact_cisco_switches_omit_environment_groups():
    panel = build_health_panel(
        "ios-basic",
        memory_ratio=0.91,
        fan_states=["critical"],
        psu_states=["critical"],
        temp_c=80,
        ports=[{"name": "Gi0/1", "utilisation": 10, "dropsRate": 0, "errors": 0}],
    )
    assert [group["id"] for group in panel["groups"]] == ["cpu", "memory"]
    assert panel["groups"][0]["value"] == "No sample"
    assert panel["groups"][1]["value"] == "91%"
    panel = build_health_panel("ios-basic", cpu=8, memory_ratio=0.4)
    assert [group["value"] for group in panel["groups"]] == ["8%", "40%"]
    assert all(group["id"] not in ("fan", "psu", "temperature") for group in panel["groups"])
    assert panel["interfacesSupported"] is True
    assert panel["interfaces"][0]["name"] == "Gi0/1"


def test_2960_temperature_can_be_status_only():
    panel = build_health_panel("ios", memory_ratio=0.4, fan_states=["normal"], psu_states=["normal"], temp_state="normal")
    temp = next(group for group in panel["groups"] if group["id"] == "temperature")
    assert temp["value"] == "normal"
    assert "Status only" in temp["detail"]
    memory = next(group for group in panel["groups"] if group["id"] == "memory")
    assert memory["value"] == "40%"


def test_aireos_second_psu_absent_is_not_a_failure():
    samples = [
        {"metric": {"__name__": "agentSwitchInfoPowerSupply1Present"}, "value": [0, "1"]},
        {"metric": {"__name__": "agentSwitchInfoPowerSupply1Operational"}, "value": [0, "1"]},
        {"metric": {"__name__": "agentSwitchInfoPowerSupply2Present"}, "value": [0, "0"]},
        {"metric": {"__name__": "agentSwitchInfoPowerSupply2Operational"}, "value": [0, "0"]},
    ]
    assert aireos_psu_states(samples) == ["normal"]


def test_access_point_pages_do_not_return_the_whole_fleet():
    rows = [{"name": "ap-%04d" % i, "mac": str(i), "wlc": "wlc-a" if i < 40 else "wlc-b", "site": "rot", "status": "up"} for i in range(80)]
    page = page_rows(rows, page=2, page_size=50, wlc="wlc-a")
    assert page["total"] == 40
    assert page["rows"] == []
    first = page_rows(rows, page=1, page_size=50, q="ap-0007")
    assert [row["name"] for row in first["rows"]] == ["ap-0007"]


def test_explain_health_matches_the_badge_and_lists_every_cause():
    assert classify_health(None, None, None, 0, 0, 0) == "unreachable"
    assert classify_health(0, 1, 10, 2, 0, 4) == "unreachable"
    assert classify_health(1, 1, 4000, 2, 0, 4) == "unreachable"
    empty = explain_health({"probe": 1, "snmpUp": 1, "lastAgeS": 10, "portsFault": 0, "portsWarn": 0, "portsTotal": 4})
    assert empty == {"health": "healthy", "items": []}
    rich = explain_health({
        "probe": 1,
        "snmpUp": 1,
        "lastAgeS": 12,
        "since": "12s ago",
        "ports": [
            {"name": "Gi1/0/2", "state": "fault", "errors": 120, "utilisation": 10},
            {"name": "Te1/1/1", "state": "up", "errors": 0, "utilisation": 91, "alias": "uplink"},
        ],
        "cpu": 96,
        "memoryPercent": 91,
        "tempC": 76,
        "fans": ["normal", "warning"],
        "psus": ["normal", "critical"],
        "apDown": 2,
        "alerts": [
            {"id": "fp", "severity": "info", "title": "Firmware notice", "detail": "behind", "status": "open", "ageSeconds": 60, "target": "system"},
            {"id": "ack", "severity": "critical", "title": "Silenced", "detail": "", "status": "acknowledged", "ageSeconds": 60},
        ],
    })
    assert rich["health"] == "critical"
    titles = [item["title"] for item in rich["items"]]
    assert "Interface down" not in titles
    assert "Interface input errors" in titles
    assert "Critical-path utilization high" in titles
    assert "CPU high" in titles
    assert "Memory high" in titles
    assert "Temperature high" in titles
    assert "Fan degraded" in titles
    assert "Power supply degraded" in titles
    assert "Access points down" in titles
    assert "Firmware notice" in titles
    assert "Silenced" not in titles
    info = next(item for item in rich["items"] if item["title"] == "Firmware notice")
    assert info["severity"] == "info"
    assert info["source"] == "alertmanager"
    errors = next(item for item in rich["items"] if item["title"] == "Interface input errors")
    assert errors["severity"] == "critical" and errors["value"] == "120/5m" and errors["since"] == "12s ago"
    assert errors["effect"] == "critical"
    quiet = explain_health({
        "probe": 1,
        "snmpUp": 1,
        "lastAgeS": 10,
        "ports": [
            {"name": "Gi1/0/8", "state": "not-connected", "errors": 0},
            {"name": "Gi1/0/9", "state": "disabled", "errors": 0},
            {"name": "Gi1/0/10", "state": "warning", "errors": 20},
        ],
    })
    assert quiet["health"] == "healthy"
    assert [item["severity"] for item in quiet["items"]] == ["warning"]
    assert quiet["items"][0]["effect"] == "healthy"
    loud = explain_health({
        "probe": 1,
        "snmpUp": 1,
        "lastAgeS": 10,
        "ports": [{"name": "Gi1/0/11", "state": "fault", "errors": 50}],
    })
    assert loud["health"] == "critical"
    only_info = explain_health({"alerts": [{"id": "i", "severity": "info", "title": "Note", "status": "open", "detail": "", "since": "1d"}]})
    assert only_info["health"] == "healthy"
    assert only_info["items"][0]["title"] == "Note"
    ap = explain_health({"apStatus": "down", "apName": "ap-1", "radios": [{"slot": "1", "utilization": 0.8}]})
    assert ap["health"] == "critical"
    assert {item["source"] for item in ap["items"]} == {"telegraf"}


def test_approve_access_point_writes_cisco_inventory():
    from ie_config.discovery import NetBoxWriter

    class Fake(NetBoxWriter):
        def __init__(self):
            self.calls = []

        def _req(self, method, path, body=None):
            self.calls.append((method, path, body))
            if method == "GET":
                return {"results": []}
            if path == "/api/dcim/devices/":
                return {"id": 9, "name": body["name"]}
            return {"id": 3}

    writer = Fake()
    made = writer.approve_access_point(
        {"name": "ap-1", "model": "C9120AXI", "serial": "FGL1", "ip": "10.8.0.10", "ios": "17.12.1", "wlc": "wlc-1"},
        role="access-point",
        site="Rotterdam",
    )
    assert made["device_id"] == 9
    posted = next(body for method, path, body in writer.calls if method == "POST" and path == "/api/dcim/devices/")
    assert posted["serial"] == "FGL1"
    assert posted["custom_fields"]["ie_parent_wlc"] == "wlc-1"
    assert posted["custom_fields"]["ie_sw_version"] == "17.12.1"
    assert posted["tags"][0]["slug"].startswith("wlc-")
    manufacturer = next(body for method, path, body in writer.calls if method == "POST" and path.startswith("/api/dcim/manufacturers/"))
    assert manufacturer["name"] == "Cisco" and manufacturer["slug"] == "cisco"
    role = next(body for method, path, body in writer.calls if method == "POST" and "/device-roles/" in path)
    assert role["slug"] == "access-point"


def test_access_point_netbox_match_prefers_serial_then_name():
    devices = [
        {"id": "1", "name": "ap-1", "serial": "OTHER", "site_name": "Rotterdam"},
        {"id": "2", "name": "sw-1", "serial": "FGL1", "site_name": "Amsterdam"},
    ]
    assert match_access_point(devices, {"name": "ap-1", "serial": "FGL1"})["id"] == "2"
    assert match_access_point(devices, {"name": "ap-1", "serial": ""})["id"] == "1"
    assert match_access_point(devices, {"name": "missing", "serial": ""}) is None
    assert suggest_ap_site({"siteTag": "rotterdam", "location": "floor"}, [{"name": "Rotterdam", "slug": "rotterdam"}]) == "Rotterdam"
    assert suggest_ap_site({"location": "Amsterdam office"}, [{"name": "Amsterdam", "slug": "ams"}]) == "Amsterdam"
    assert suggest_ap_site({"site": "Lab"}, []) == "Lab"


def test_module_map_picks_wlc_platform_and_skips_aps():
    import yaml
    mapping = yaml.safe_load((ROOT / "config" / "discovery" / "module-map.yml").read_text())
    choose = _sd().choose_module
    iosxe, auth = choose("wireless-controller", "cisco", "ios-xe", "", "", mapping)
    assert "cisco_wlc_iosxe" in iosxe.split(",")
    assert "cisco_wlc_universal" not in iosxe.split(",")
    assert "cisco_entity_sensor" in iosxe.split(",")
    assert auth == "ie_wlc_v2"
    aireos, _auth = choose("wireless-controller", "cisco", "aireos", "", "", mapping)
    assert "cisco_wlc_aireos" in aireos.split(",")
    assert "cisco_wlc_universal" not in aireos.split(",")
    assert choose("access-point", "cisco", "ios-xe", "", "", mapping)[0] == "skip"
    # Unlabelled access switches keep the existing module list.
    access, access_auth = choose("access-switch", "cisco", "", "", "", mapping)
    assert access.split(",")[:6] == ["if_mib", "cisco_environ", "cisco_mem", "cisco_pro", "cisco_cdp", "lldp"]
    assert access_auth == "ntt_snmpv3_auth"
    palo, _ = choose("core-firewall", "palo-alto", "pan-os", "", "", mapping)
    assert palo == "if_mib,paloalto_health,uptime"
    forti, _ = choose("sdwan", "fortinet", "fortigate", "", "", mapping)
    assert "fortinet_health" in forti.split(",")
    assert "if_mib_fortigate" in forti.split(",")
