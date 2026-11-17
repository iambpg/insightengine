"""Site briefing text. No Prometheus or Loki."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ie_config.site_briefing import build_briefing, classify_logs, fortigate_limits, link_points, sla_points, talkers_from


def _device(name, role, form, health="healthy"):
    return {"hostname": name, "role": role, "formFactor": form, "health": health}


def test_empty_site_says_there_is_nothing_to_summarise():
    body = build_briefing(
        window_label="the past 24 hours", devices=[], logs=[],
        cpu=None, memory=None, port_errors=None, ports_down=None,
        clients=None, noise=None, interference=None,
        wan_in=None, wan_out=None, wan_known=False, loss=None, talkers=[],
    )
    assert "no devices yet" in body["summary"]
    assert body["talkers"] == []


def test_summary_uses_logs_cpu_and_a_client_count():
    body = build_briefing(
        window_label="the past 6 hours",
        devices=[
            _device("sw1", "Access switch", "access-switch-48"),
            _device("ap1", "Access point", "ceiling-ap", "unreachable"),
        ],
        logs=[{
            "at": "2026-11-12 21:00:00",
            "hostname": "sw1",
            "severity": "notice",
            "message": "%SYS-5-CONFIG_I: Configured from console by admin",
        }, {
            "at": "2026-11-12 21:05:00",
            "hostname": "sw1",
            "severity": "notice",
            "message": "snmp community secret-value must not be repeated",
        }],
        cpu=[("sw1", 34)],
        memory=[("sw1", 61)],
        port_errors=[("sw1", 0)],
        ports_down=[("sw1", 1)],
        clients=18,
        noise=-91,
        interference=0.08,
        wan_in=None,
        wan_out=None,
        wan_known=False,
        loss=None,
        talkers=[{"device": "sw1", "port": "Gi1/0/1", "inMbps": 12.4, "outMbps": 3.2}],
    )
    assert "highest CPU was 34% on sw1" in body["summary"]
    assert "18 Wi-Fi clients are connected" in body["summary"]
    assert "secret-value" not in body["summary"]
    logs = next(section for section in body["sections"] if section["id"] == "logs")
    config = next(note for note in logs["notices"] if note["id"] == "config")
    assert config["items"][0]["detail"].startswith("%SYS-5-CONFIG_I")
    assert "secret-value" not in logs["text"]
    assert all("secret-value" not in item["detail"] for note in logs["notices"] for item in note["items"])
    wifi = next(section for section in body["sections"] if section["id"] == "wifi")
    assert "Clients are not listed" in wifi["text"]
    assert "quiet floor" in wifi["text"]
    assert "Interference is low" in wifi["text"]
    assert "ap1" not in wifi["text"]


def test_talkers_skip_virtual_ports_and_rank_the_busiest():
    inbound = [
        {"metric": {"hostname": "sw1", "ifName": "Vlan1"}, "value": [0, "999999999"]},
        {"metric": {"hostname": "sw1", "ifName": "Gi1/0/1"}, "value": [0, str(10_000_000)]},
        {"metric": {"hostname": "sw1", "ifName": "Gi1/0/2"}, "value": [0, str(1_000_000)]},
    ]
    ranked = talkers_from(inbound, [], 100)
    assert [row["port"] for row in ranked] == ["Gi1/0/1", "Gi1/0/2"]
    assert ranked[0]["inMbps"] > ranked[1]["inMbps"]


def test_classify_logs_counts_link_and_config_separately():
    counted = classify_logs([
        {"message": "%LINK-3-UPDOWN: Interface Gi1/0/1, changed state to down", "severity": "error"},
        {"message": "%SYS-5-CONFIG_I: Configured from vty", "severity": "notice"},
    ])
    assert counted["linkDown"] == 1
    assert counted["configChanges"] == 1
    assert counted["problems"] == 0


def test_sla_points_keep_throughput_and_only_a_real_limiter():
    inbound = [{"values": [[1_700_000_000, "1.5"], [1_700_000_300, "2"]]}]
    outbound = [{"values": [[1_700_000_000, "0.25"]]}]
    body = sla_points(inbound, outbound, 100)
    assert body["limiterMbps"] == 100
    assert [point["inMbps"] for point in body["points"]] == [1.5, 2]
    assert body["points"][0]["outMbps"] == 0.25
    assert sla_points([], [], 0)["limiterMbps"] is None
    assert sla_points([], [], None)["note"]


def test_fortigate_limits_keep_each_interface_and_drop_zeros():
    inbound = [
        {"metric": {"ifName": "internal1"}, "value": [0, "0"]},
        {"metric": {"ifName": "wan1"}, "value": [0, "51200"]},
        {"metric": {"ifName": "wan2"}, "value": [0, "20480"]},
    ]
    outbound = [
        {"metric": {"ifName": "wan1"}, "value": [0, "102400"]},
        {"metric": {"ifName": "wan2"}, "value": [0, "20480"]},
    ]
    limits = fortigate_limits(inbound, outbound)
    assert [item["name"] for item in limits["interfaces"]] == ["wan1", "wan2"]
    assert limits["interfaces"][0]["inMbps"] == 51.2
    assert limits["interfaces"][0]["outMbps"] == 102.4
    assert limits["limiterInMbps"] == 71.68
    assert limits["limiterOutMbps"] == 122.88


def test_link_points_keep_each_interface_apart():
    inbound = [{"metric": {"ifName": "wan1"}, "values": [[10, "1.5"], [15, "2"]]}, {"metric": {"ifName": "wan2"}, "values": [[10, "4"]]}]
    outbound = [{"metric": {"ifName": "wan1"}, "values": [[10, "0.5"]]}]
    links = link_points(inbound, outbound, ["wan1", "wan2"])
    assert [link["name"] for link in links] == ["wan1", "wan2"]
    assert links[0]["points"][0]["inMbps"] == 1.5
    assert links[0]["points"][0]["outMbps"] == 0.5
    assert links[1]["points"][0]["inMbps"] == 4
    assert links[1]["points"][0]["outMbps"] == 0
