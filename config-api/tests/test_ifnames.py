"""Interface name normalisation, port state, and neighbour merge."""

from ie_config.fleet import _canonical_port, _overlay_neighbours, _overlay_port_state, _port_state
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
    assert _port_state("down", "up", 0, 0) == "fault"
    assert _port_state(2, 1, 0, 0) == "fault"
    assert _port_state("up", "up", 0, 0) == "up"
    assert _port_state("down", "down", 0, 0) == "disabled"


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
        [{"id": "9", "hostname": "dist", "mgmtIp": "10.129.32.1"}],
        merged,
        [".pnp.co.za"],
    )
    assert ports[0]["neighbour"]["source"] == "netdisco"
    assert ports[0]["neighbour"]["deviceId"] == "9"
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
