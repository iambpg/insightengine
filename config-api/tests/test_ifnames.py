"""Interface name normalisation, port state, and neighbour merge."""

from ie_config.fleet import (
    _canonical_port,
    _is_virtual_port,
    _overlay_neighbours,
    _overlay_port_state,
    _port_state,
    _present_port,
    parse_system_metrics,
)
from ie_config.ifnames import canonical_iface, names_match
from ie_config.neighbours import merge_neighbors, neighbors_from_cdp, neighbors_from_lldp, parse_snmp_address


PAIRS = [
    ("FastEthernet0/21", "Fa0/21"),
    ("fastethernet0/21", "FA0/21"),
    ("GigabitEthernet1/0/1", "Gi1/0/1"),
    ("GigabitEthernet0/1", "gi0/1"),
    ("TenGigabitEthernet1/1/1", "Te1/1/1"),
    ("TenGigEthernet1/0/1", "Te1/0/1"),
    ("TwentyFiveGigE1/1/1", "Twe1/1/1"),
    ("TwentyFiveGigabitEthernet1/0/1", "twe1/0/1"),
    ("FortyGigabitEthernet1/0/1", "Fo1/0/1"),
    ("FortyGigE1/0/1", "fo1/0/1"),
    ("HundredGigE1/0/1", "Hu1/0/1"),
    ("HundredGigabitEthernet1/0/1", "hu1/0/1"),
    ("Ethernet1/1", "Eth1/1"),
    ("Ethernet1/1", "Et1/1"),
    ("Port-channel1", "Po1"),
    ("Port-Channel10", "po10"),
    ("Vlan100", "Vl100"),
    ("Loopback0", "Lo0"),
    ("Tunnel0", "Tu0"),
    ("Management0", "Ma0"),
    ("mgmt0", "Management0"),
    ("port1", "port 1"),
    ("Port1", "PORT1"),
    ("wan1", "WAN 1"),
    ("ha1", "HA1"),
    ("internal1", "Internal 1"),
    ("fortilink", "FortiLink"),
    ("ethernet1/1", "Eth1/1"),
    ("ethernet1/1.100", "eth1/1.100"),
    ("ae1", "AE1"),
    ("ae1", "ae-1"),
    ("ae1.100", "AE1.100"),
    ("tunnel.1", "Tu.1"),
    ("loopback.1", "Lo.1"),
    ("vlan.100", "Vl.100"),
]


def test_long_and_short_names_share_one_key():
    for left, right in PAIRS:
        assert canonical_iface(left) == canonical_iface(right), (left, right)
        assert names_match(left, right)


def test_fortigate_lan_ports_are_physical():
    assert not _is_virtual_port("internal1")
    assert not _is_virtual_port("internal5")
    assert not _is_virtual_port("wan1")
    assert _is_virtual_port("internal")
    assert _is_virtual_port("Internal-Data0/0")
    assert _is_virtual_port("Vlan100")
    assert _is_virtual_port("Loopback0")


def test_different_ports_do_not_match():
    assert not names_match("GigabitEthernet0/1", "Gi0/2")
    assert not names_match("port1", "Po1")
    assert not names_match("FastEthernet0/21", "FastEthernet0/22")
    assert canonical_iface("") == ""


def test_unconfirmed_enabled_port_is_unknown_and_admin_down_is_disabled():
    unknown = _canonical_port({"name": "FastEthernet0/21", "enabled": True, "type": "100base-tx"})
    assert unknown["state"] == "unknown"
    disabled = _canonical_port({"name": "FastEthernet0/22", "enabled": False})
    assert disabled["state"] == "disabled"
    assert _port_state("down", "up", 0, 0) == "not-connected"
    assert _port_state(2, 1, 0, 0) == "not-connected"
    assert _port_state("up", "up", 0, 0) == "up"
    assert _port_state("down", "down", 0, 0) == "disabled"
    assert _port_state("down", "down", 20, 0) == "warning"
    assert _port_state("down", "down", 50, 0) == "fault"
    assert _port_state("up", "up", 19, 0) == "up"
    assert _port_state("up", "up", 20, 0) == "warning"
    assert _port_state("notPresent", "up", 0, 0) == "disabled"


def test_overlay_matches_long_netbox_name_to_short_ifname_and_alias():
    ports = [
        _canonical_port({"name": "FastEthernet0/21", "enabled": True}),
        _canonical_port({"name": "FastEthernet0/22", "enabled": True}),
        _canonical_port({"name": "GigabitEthernet0/1", "enabled": False}),
    ]
    prom = [{
        "id": "10021",
        "name": "Fa0/21",
        "names": ["Fa0/21", "FastEthernet0/21", "uplink"],
        "state": "up",
        "utilisation": 4.5,
        "errors": 0,
        "speed": "100 Mbps",
        "type": "RJ45",
        "inBps": 12000.0,
        "outBps": 34000.0,
    }, {
        "id": "10022",
        "name": "Fa0/22",
        "names": ["Fa0/22"],
        "state": "fault",
        "utilisation": 0,
        "errors": 3,
        "speed": "—",
        "type": "RJ45",
        "inBps": 0,
        "outBps": 0,
    }]
    overlaid = _overlay_port_state(ports, prom)
    assert overlaid[0]["state"] == "up"
    assert overlaid[0]["id"] == "10021"
    assert overlaid[0]["inBps"] == 12000.0
    assert overlaid[0]["speed"] == "100 Mbps"
    assert overlaid[1]["state"] == "fault"
    assert overlaid[2]["state"] == "disabled"
    # alias on the Prometheus side still finds the NetBox name via the shared keys
    by_alias = _overlay_port_state(
        [_canonical_port({"name": "uplink", "enabled": True})],
        prom,
    )
    assert by_alias[0]["state"] == "up"
    assert by_alias[0]["names"] == ["Fa0/21", "FastEthernet0/21"]
    assert by_alias[0]["description"] == "uplink"


def test_port_shows_short_name_long_name_and_description():
    port = _canonical_port({
        "name": "FastEthernet0/21",
        "description": "till",
        "enabled": True,
        "type": "100base-tx",
    })
    assert port["description"] == "till"
    overlaid = _overlay_port_state([port], [{
        "id": "10021",
        "name": "Fa0/21",
        "names": ["Fa0/21", "FastEthernet0/21", "!Uplink_to_AP"],
        "alias": "!Uplink_to_AP",
        "description": "FastEthernet0/21",
        "state": "up",
        "utilisation": 1,
        "errors": 0,
        "speed": "100 Mbps",
        "type": "RJ45",
    }])
    assert overlaid[0]["name"] == "FastEthernet0/21"
    assert overlaid[0]["names"] == ["Fa0/21"]
    assert overlaid[0]["description"] == "!Uplink_to_AP"
    shown = _present_port({
        "id": "1",
        "name": "Gi1/0/1",
        "names": ["Gi1/0/1", "GigabitEthernet1/0/1", "ARMS_SERVER"],
        "alias": "ARMS_SERVER",
        "description": "GigabitEthernet1/0/1",
        "state": "up",
    })
    assert shown["name"] == "Gi1/0/1"
    assert shown["names"] == ["GigabitEthernet1/0/1"]
    assert shown["description"] == "ARMS_SERVER"
    bluetooth = _present_port({
        "name": "Bl0/4",
        "names": ["Bl0/4", "Bluetooth0/4"],
        "description": "Bluetooth0/4",
        "alias": "",
    })
    assert bluetooth["names"] == ["Bluetooth0/4"]
    assert "description" not in bluetooth
    labeled = _overlay_port_state(
        [_canonical_port({"name": "TILL19", "enabled": True})],
        [{
            "name": "Gi1/0/10",
            "names": ["Gi1/0/10", "GigabitEthernet1/0/10", "TILL19"],
            "alias": "TILL19",
            "description": "GigabitEthernet1/0/10",
            "state": "up",
        }],
    )
    assert labeled[0]["description"] == "TILL19"
    assert labeled[0]["names"] == ["Gi1/0/10", "GigabitEthernet1/0/10"]
    null_port = _present_port({
        "name": "Nu0",
        "names": ["Nu0", "Null0"],
        "description": "Null0",
        "alias": "",
    })
    assert null_port["names"] == ["Null0"]
    assert "description" not in null_port


def test_cdp_neighbours_merge_with_netdisco_and_normalised_ports():
    prom = [{"id": "10021", "name": "Fa0/21"}]
    cdp = neighbors_from_cdp(
        [{"metric": {"cdpCacheDeviceId": "dist.pnp.co.za (FOC1234)", "cdpCacheIfIndex": "10021", "cdpCacheDeviceIndex": "1"}, "value": [1, "1"]}],
        [{"metric": {"cdpCacheDevicePort": "Gi1/0/1", "cdpCacheIfIndex": "10021", "cdpCacheDeviceIndex": "1"}, "value": [1, "1"]}],
        [{"metric": {"cdpCacheAddress": "0x0A812001", "cdpCacheIfIndex": "10021", "cdpCacheDeviceIndex": "1"}, "value": [1, "1"]}],
        [],
        prom,
        [".pnp.co.za"],
    )
    assert cdp[0]["localPort"] == "Fa0/21"
    assert cdp[0]["remoteName"] == "dist"
    assert cdp[0]["remoteAddress"] == "10.129.32.1"
    assert cdp[0]["source"] == "cdp"
    assert parse_snmp_address("0a:81:20:01") == "10.129.32.1"
    netdisco = [{
        "localPort": "FastEthernet0/21",
        "remoteName": "dist",
        "remotePort": "Gi1/0/1",
        "remoteAddress": "10.129.32.1",
        "protocol": "cdp",
        "source": "netdisco",
    }]
    extra = neighbors_from_cdp(
        [{"metric": {"cdpCacheDeviceId": "ap-hall.pnp.co.za", "cdpCacheIfIndex": "10001", "cdpCacheDeviceIndex": "1", "ifName": "Fa0/1"}, "value": [1, "1"]}],
        [{"metric": {"cdpCacheDevicePort": "Gi0", "cdpCacheIfIndex": "10001", "cdpCacheDeviceIndex": "1"}, "value": [1, "1"]}],
        [],
        [],
        [{"id": "10001", "name": "Fa0/1"}],
        [".pnp.co.za"],
    )
    merged = merge_neighbors(netdisco, cdp + extra)
    assert len(merged) == 2
    assert merged[0]["source"] == "netdisco"
    assert merged[1]["remoteName"] == "ap-hall"
    assert merged[1]["source"] == "cdp"
    ports = _overlay_neighbours(
        [_canonical_port({"name": "FastEthernet0/21", "enabled": True}), _canonical_port({"name": "FastEthernet0/1", "enabled": True})],
        [{"name": "FastEthernet0/21", "remoteName": "dist", "remotePort": "Gi1/0/1", "remoteAddress": "10.129.32.1"}],
        [{"id": "9", "hostname": "dist", "mgmtIp": "10.129.32.1", "role": "Access switch", "formFactor": "access-switch-24"}],
        merged,
        [".pnp.co.za"],
    )
    assert ports[0]["neighbour"]["source"] == "netdisco"
    assert ports[0]["neighbour"]["deviceId"] == "9"
    assert ports[0]["neighbour"]["formFactor"] == "access-switch-24"
    assert ports[1]["neighbour"]["deviceId"] == ""
    assert ports[1]["neighbour"]["device"] == "ap-hall"
    assert ports[1]["neighbour"]["source"] == "cdp"


def test_lldp_uses_local_port_id_and_management_address():
    rows = neighbors_from_lldp(
        [{"metric": {"lldpRemSysName": "core.example.net", "lldpRemTimeMark": "0", "lldpRemLocalPortNum": "21", "lldpRemIndex": "1"}, "value": [1, "1"]}],
        [{"metric": {"lldpRemPortId": "Gi1/0/48", "lldpRemTimeMark": "0", "lldpRemLocalPortNum": "21", "lldpRemIndex": "1"}, "value": [1, "1"]}],
        [],
        [{"metric": {"lldpRemManAddr": "0x0A000001", "lldpRemManAddrSubtype": "ipV4", "lldpRemTimeMark": "0", "lldpRemLocalPortNum": "21", "lldpRemIndex": "1"}, "value": [1, "2"]}],
        [{"metric": {"lldpLocPortNum": "21", "lldpLocPortId": "Fa0/21"}, "value": [1, "1"]}],
        [{"id": "10021", "name": "Fa0/21", "names": ["Fa0/21"]}],
        [".example.net"],
    )
    assert rows[0]["remoteName"] == "core"
    assert rows[0]["remotePort"] == "Gi1/0/48"
    assert rows[0]["remoteAddress"] == "10.0.0.1"
    assert rows[0]["localPort"] == "Fa0/21"
    assert rows[0]["source"] == "lldp"


def test_ios_xe_system_metrics_keep_version_and_chassis_serial():
    text = "\n".join([
        'sysDescr{sysDescr="Cisco IOS Software [Bengaluru], Catalyst L3 Switch Software (CAT9K_LITE_IOSXE), Version 17.6.3, RELEASE SOFTWARE (fc4)\r\\nTechnical Support: http://www.cisco.com/techsupport"} 1',
        'sysUpTime 3679792006',
        'entPhysicalModelName{entPhysicalIndex="1",entPhysicalModelName="C9200L-24P-4G",entPhysicalSerialNum="FOC26425BF2",entPhysicalSoftwareRev=""} 1',
        'entPhysicalModelName{entPhysicalIndex="1000",entPhysicalModelName="C9200L-24P-4G",entPhysicalSerialNum="FOC26425BF2",entPhysicalSoftwareRev="Bengaluru 17.06.03"} 1',
        'entPhysicalModelName{entPhysicalIndex="2000",entPhysicalModelName="C9200L-24P-4G",entPhysicalSerialNum="FOC26499XYZ",entPhysicalSoftwareRev="Bengaluru 17.06.03"} 1',
        'entPhysicalModelName{entPhysicalIndex="1013",entPhysicalModelName="PWR-C5-600WAC",entPhysicalSerialNum="QCS26294RKJ",entPhysicalSoftwareRev=""} 1',
        'entPhysicalModelName{entPhysicalIndex="1092",entPhysicalModelName="SFP-10G-SR",entPhysicalSerialNum="ACW26211JF7",entPhysicalSoftwareRev=""} 1',
    ])
    facts = parse_system_metrics(text)
    assert facts["firmware"] == "17.6.3"
    assert facts["part"] == "C9200L-24P-4G"
    assert facts["serial"] == "FOC26425BF2, FOC26499XYZ"
    assert facts["uptime"] == 3679792006.0
    coded = parse_system_metrics(
        'entPhysicalModelName{entPhysicalIndex="2000",entPhysicalModelName="C9800-80-K9",entPhysicalSerialNum="FOX2643QALH",entPhysicalSoftwareRev="Dublin 17.12.05"} 1\n'
        'entPhysicalModelName{entPhysicalIndex="24",entPhysicalModelName="C9800-AC-1100W",entPhysicalSerialNum="ART2718F845",entPhysicalSoftwareRev=""} 1\n'
    )
    assert coded["firmware"] == "17.12.05"
    assert coded["serial"] == "FOX2643QALH"
    assert coded["part"] == "C9800-80-K9"
