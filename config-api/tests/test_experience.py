"""Service experience config generation, NetBox SD and field ensure. No devices."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "config-api"))

from ie_config.experience import (  # noqa: E402
    build_experience,
    ip_sla_config,
    is_cedge,
    telemetry_config,
)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _render():
    return _load(ROOT / "config" / "telegraf" / "wlc" / "render_wlc.py", "render_wlc_experience")


def _sd():
    return _load(ROOT / "netbox" / "netbox_lists" / "sd.py", "netbox_lists_sd_experience")


def _fields():
    return _load(ROOT / "netbox" / "experience-fields" / "ensure_fields.py", "ensure_fields_experience")


def _target(platform: str, name: str = "wlc-a") -> dict:
    return {
        "targets": ["10.1.1.8"],
        "labels": {
            "__meta_netbox_name": name,
            "__meta_netbox_platform": platform,
            "__meta_netbox_role": "wireless-controller",
            "__meta_netbox_site_name": "rotterdam",
            "__meta_netbox_snmp_auth": "ie_wlc_v2",
        },
    }


def test_9800_snmp_tables_are_not_rendered():
    text = _render().render([_target("ios-xe", "wlc-9800")], {"SNMP_V2_COMMUNITY": "public"})
    assert "[[inputs.snmp]]" not in text
    assert "MDT supersedes" in text
    assert "wlc-9800" in text


def test_legacy_flag_restores_9800_snmp_tables():
    text = _render().render(
        [_target("ios-xe")],
        {"SNMP_V2_COMMUNITY": "public", "IE_WLC_LEGACY_SNMP": "1", "IE_WLC_TABLE": "status"},
    )
    assert "[[inputs.snmp]]" in text
    assert "1.3.6.1.4.1.9.9.513.1.1.1.1.5" in text


def test_aireos_keeps_load_table_and_station_rssi():
    text = _render().render([_target("aireos", "wlc-aireos")], {"SNMP_V2_COMMUNITY": "public"})
    assert "1.3.6.1.4.1.14179.2.2.13.1.3" in text
    assert "1.3.6.1.4.1.14179.2.1.6.1.1" in text
    assert "1.3.6.1.4.1.14179.2.1.6.1.26" in text
    assert "bsnMobile" not in text or "station" in text
    assert 'wlc_table = "stations"' in text
    assert "store_clients" in text


def test_gnmi_dial_in_is_rendered_for_a_9800_only_when_asked():
    env = {
        "IE_WLC_MDT_TRANSPORT": "gnmi",
        "IE_GNMI_USER": "collector",
        "IE_GNMI_PASSWORD": "gnmi-secret",
    }
    text = _render().render([_target("ios-xe", "wlc-9800")], env)
    assert "[[inputs.gnmi]]" in text
    assert "traffic-stats" in text
    assert "[[inputs.snmp]]" not in text
    assert "gnmi-secret" in text
    aire = _render().render([_target("aireos")], env | {"SNMP_V2_COMMUNITY": "public"})
    assert "[[inputs.gnmi]]" not in aire
    assert "[[inputs.snmp]]" in aire


def test_telemetry_cli_for_9800_is_paste_only():
    body = telemetry_config(
        {"name": "wlc-9800", "ip": "10.9.0.8", "role": "wireless-controller", "platform": "ios-xe", "model": "C9800-80"},
        receiver="10.1.1.50",
    )
    assert body["configured"] is True
    assert body["pushed"] is False
    assert "does not push" in body["config"]
    assert "/wireless-client-oper:client-oper-data/traffic-stats" in body["config"]
    assert "/wireless-rrm-oper:rrm-oper-data/rrm-measurement" in body["config"]
    assert "/wireless-access-point-oper:access-point-oper-data/capwap-data" in body["config"]
    assert "update-policy on-change" in body["config"]
    assert "update-policy periodic 6000" in body["config"]
    assert "10.1.1.50" in body["config"]
    assert "receiver ip address 10.1.1.50 57500 protocol grpc-tcp" in body["config"]
    assert "57000" not in body["config"]


def test_aireos_telemetry_says_snmp():
    body = telemetry_config({"name": "wlc-a", "ip": "10.9.0.9", "role": "wireless-controller", "platform": "aireos"})
    assert body["configured"] is False
    assert "AireOS" in body["reason"]
    assert body["config"] == ""


def test_cedge_cli_is_not_the_fortigate_role():
    assert is_cedge("sdwan", "fortigate", "fortinet") is False
    assert is_cedge("cedge", "ios-xe", "cisco", "C8300") is True
    body = telemetry_config(
        {"name": "edge-1", "ip": "10.4.0.1", "role": "cedge", "platform": "ios-xe", "manufacturer": "cisco"},
        receiver="10.1.1.50",
    )
    assert body["pushed"] is False
    assert "/sdwan-oper:sdwan-oper-data/app-route/statistics" in body["config"]
    assert "/sdwan-oper:sdwan-oper-data/bfd/sessions" in body["config"]
    assert "wireless-client-oper" not in body["config"]


def test_ip_sla_needs_a_vbs_address_and_is_not_pushed():
    router = {"name": "edge-rot", "ip": "10.8.0.1", "role": "distribution-switch", "platform": "ios-xe", "site": "Rotterdam"}
    missing = ip_sla_config(router, {"name": "Rotterdam"})
    assert missing["configured"] is False
    assert "not configured" in missing["reason"]
    assert missing["pushed"] is False
    ready = ip_sla_config(router, {"name": "Rotterdam", "vbs_server_ip": "10.50.0.9", "vbs_server_port": 9999})
    assert ready["configured"] is True
    assert ready["pushed"] is False
    assert "tcp-connect 10.50.0.9 9999 source-ip 10.8.0.1" in ready["config"]
    assert "udp-jitter 10.50.0.9 9999" in ready["config"]
    assert "icmp-jitter 10.50.0.9 source-ip 10.8.0.1" in ready["config"]
    assert "does not push" in ready["config"]
    firewall = ip_sla_config({"name": "fw", "ip": "10.8.0.2", "role": "sdwan", "platform": "fortigate"}, {"vbs_server_ip": "10.50.0.9"})
    assert firewall["configured"] is False


def test_summary_not_configured_states():
    body = build_experience([], [], [])
    assert body["wlc"]["configured"] is False
    assert "not configured" in body["wlc"]["reason"]
    assert body["sdwan"]["configured"] is False
    assert "cEdge" in body["sdwan"]["reason"]
    assert body["vbs"]["configured"] is False
    assert body["thirdParties"]["configured"] is False
    ready = build_experience(
        [{"name": "wlc-9800", "role": "wireless-controller", "platform": "ios-xe", "site": "Rotterdam", "ip": "10.0.0.1"}],
        [{"name": "Rotterdam", "vbs_server_ip": "10.50.0.9", "vbs_server_port": 9999}],
        [{"name": "example-bank", "tags": ["bank"], "probe": "tcp", "address": "203.0.113.10", "port": 443, "site": "Rotterdam"}],
    )
    assert ready["wlc"]["controllers"][0]["transport"] == "mdt"
    assert ready["vbs"]["sites"][0]["vbsServerPort"] == 9999
    assert ready["thirdParties"]["targets"][0]["kind"] == "bank"


def test_http_sd_filters_probe_and_skips_empty_vbs():
    sd = _sd()
    services = [
        {"name": "card-net", "tags": ["bank"], "probe": "tcp", "address": "203.0.113.10", "port": "443", "site": "Rotterdam"},
        {"name": "time", "tags": ["third-party"], "probe": "icmp", "address": "198.51.100.8", "port": "", "site": "Rotterdam"},
        {"name": "no-probe", "tags": ["bank"], "probe": "", "address": "203.0.113.11", "port": "443"},
        {"name": "inside", "tags": ["access"], "probe": "icmp", "address": "10.0.0.1"},
    ]
    banks = sd.service_targets(services, "bank", "tcp")
    assert [row["targets"][0] for row in banks] == ["203.0.113.10:443"]
    assert banks[0]["labels"]["__meta_netbox_kind"] == "bank"
    icmp = sd.service_targets(services, "third-party", "icmp")
    assert icmp[0]["targets"] == ["198.51.100.8"]
    assert sd.vbs_targets([{"name": "Empty"}, {"name": "Rotterdam", "vbs_server_ip": "10.50.0.9", "vbs_server_port": 9999}])[0]["labels"]["__meta_netbox_site_name"] == "Rotterdam"


def test_module_map_adds_rttmon_and_cedge_bfd_without_touching_fortigate():
    mapping = yaml.safe_load((ROOT / "config" / "discovery" / "module-map.yml").read_text())
    choose = _sd().choose_module
    cedge, auth = choose("cedge", "cisco", "ios-xe", "", "", mapping)
    assert "cisco_rttmon" in cedge.split(",")
    assert "cisco_sdwan_bfd" in cedge.split(",")
    assert auth == "ntt_snmpv3_auth"
    forti, _ = choose("sdwan", "fortinet", "fortigate", "", "", mapping)
    assert "cisco_sdwan_bfd" not in forti.split(",")
    assert "fortinet_health" in forti.split(",")
    wlc, _ = choose("wireless-controller", "cisco", "ios-xe", "", "", mapping)
    assert "cisco_wlc_iosxe" in wlc.split(",")
    assert "cisco_rttmon" not in wlc.split(",")
    ios, _ = choose("router", "cisco", "ios", "", "", mapping)
    assert "cisco_rttmon" in ios.split(",")


def test_blackbox_jobs_refresh_within_five_minutes():
    text = (ROOT / "config" / "prometheus" / "prometheus.yml").read_text()
    for job in (
        "blackbox-third-party-icmp",
        "blackbox-third-party-tcp",
        "blackbox-bank-icmp",
        "blackbox-bank-tcp",
        "blackbox-vbs-icmp",
    ):
        assert "job_name: %s" % job in text
    assert text.count("prometheus-services/") == 4
    assert "prometheus-vbs/" in text
    assert "refresh_interval: 5m" in text.split("blackbox-third-party-icmp", 1)[1]


def test_experience_fields_are_idempotent_and_seed_nothing():
    fields = _fields()

    class Mem:
        def __init__(self):
            self.rows = []
            self.posts = 0

        def get(self, path: str):
            parsed = urlparse(path)
            query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
            found = []
            for row in self.rows:
                if not parsed.path.startswith(row["_collection"]):
                    continue
                if query.get("name") and row.get("name") != query["name"]:
                    continue
                if query.get("slug") and row.get("slug") != query["slug"]:
                    continue
                found.append(row)
            return 200, {"results": found}

        def post(self, path: str, body: dict):
            self.posts += 1
            row = dict(body)
            row["id"] = len(self.rows) + 1
            row["_collection"] = path.rstrip("/")
            self.rows.append(row)
            return 201, row

        def patch(self, path: str, body: dict):
            number = int(path.rstrip("/").split("/")[-1])
            for row in self.rows:
                if row["id"] == number:
                    row.update(body)
                    return 200, row
            return 404, {}

    api = Mem()
    first = fields.ensure_all(api)
    posts = api.posts
    assert posts == 7
    assert first["fields"]["vbs_server_port"] == "created"
    second = fields.ensure_all(api)
    assert api.posts == posts
    assert second["fields"]["vbs_server_ip"] == "present"
    assert second["tags"]["bank"] == "present"
    names = [row.get("name") for row in api.rows]
    assert "vbs_server_ip" in names and "probe" in names and "target" in names
    assert not any(row.get("address") or row.get("primary_ip4") for row in api.rows)
    port = next(row for row in api.rows if row.get("name") == "vbs_server_port")
    assert port["default"] == 9999


def test_snmp_modules_cover_rttmon_and_bfd_state():
    document = yaml.safe_load((ROOT / "snmp" / "out" / "snmp.yml").read_text())
    rtt = document["modules"]["cisco_rttmon"]
    names = [metric["name"] for metric in rtt["metrics"]]
    assert "rttMonLatestRttOperCompletionTime" in names
    assert "rttMonLatestJitterOperAvgJitter" in names
    assert "rttMonLatestJitterOperPacketLossSD" in names
    assert "rttMonJitterStatsAvgJitter" in names
    bfd = document["modules"]["cisco_sdwan_bfd"]["metrics"][0]
    assert bfd["name"] == "ciscoBfdSessState"
    assert bfd["oid"] == "1.3.6.1.4.1.9.10.137.1.2.1.6"
