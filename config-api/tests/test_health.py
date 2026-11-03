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
    classify_profile,
    page_rows,
)


def _sd():
    path = ROOT / "netbox" / "netbox_lists" / "sd.py"
    spec = importlib.util.spec_from_file_location("netbox_lists_sd_health", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_profiles_cover_the_supported_device_types():
    assert classify_profile("access-switch", "ios", "Cisco", "WS-C2960X-48FPS-L") == "ios"
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
    assert palo == "if_mib,paloalto_health"
    forti, _ = choose("sdwan", "fortinet", "fortigate", "", "", mapping)
    assert "fortinet_health" in forti.split(",")
    assert "if_mib_fortigate" in forti.split(",")
