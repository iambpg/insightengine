"""Stack badge: NetBox chassis, then stackwise, then a single tile."""

from ie_config.stack import member_from_metric, paint_member_health, resolve_stack, stack_from_snmp


def _peer(id_, position, master_id, model="C9300-48P", serial=""):
    return {
        "id": str(id_),
        "vc_id": "7",
        "vc_position": position,
        "vc_master_id": str(master_id),
        "model": model,
        "serial": serial or ("SER%02d" % id_),
    }


def _stack(master_id, count):
    peers = [_peer(index, index, master_id) for index in range(1, count + 1)]
    return resolve_stack(peers[0], peers, role_slug="access-switch", form_factor="access-switch-48")


def test_standalone_switch_is_one_tile():
    stack = resolve_stack(
        {"id": "1", "model": "C9300-24P", "serial": "FCW1"},
        [],
        [],
        [],
        role_slug="access-switch",
        form_factor="access-switch-24",
    )
    assert stack["source"] == "standalone"
    assert stack["members"] == [{
        "number": 1, "role": "active", "model": "C9300-24P", "serial": "FCW1", "state": "", "master": True,
    }]


def test_stack_of_two_master_is_member_1():
    stack = _stack(1, 2)
    assert stack["source"] == "netbox"
    assert [item["number"] for item in stack["members"]] == [1, 2]
    assert [item["master"] for item in stack["members"]] == [True, False]
    assert stack["members"][0]["role"] == "active"
    assert stack["members"][1]["role"] == "member"
    assert stack["members"][0]["serial"] == "SER01"


def test_stack_of_two_master_is_member_2():
    stack = _stack(2, 2)
    assert [item["number"] for item in stack["members"]] == [1, 2]
    assert [item["master"] for item in stack["members"]] == [False, True]
    assert stack["members"][1]["role"] == "active"
    assert stack["members"][0]["role"] == "member"


def test_stack_of_eight_master_is_member_5():
    stack = _stack(5, 8)
    assert [item["number"] for item in stack["members"]] == list(range(1, 9))
    assert [item["number"] for item in stack["members"] if item["master"]] == [5]
    assert stack["members"][4]["role"] == "active"
    assert stack["members"][4]["model"] == "C9300-48P"


def test_no_stack_data_is_a_single_tile():
    stack = resolve_stack(
        {"id": "9", "role_slug": "core-switch"},
        [],
        None,
        None,
        role_slug="core-switch",
        form_factor="modular-chassis",
    )
    assert stack["source"] == "standalone"
    assert [item["number"] for item in stack["members"]] == [1]
    assert stack["members"][0]["master"] is True


def test_positions_are_not_renumbered_and_netbox_beats_snmp():
    peers = [_peer(1, 1, 1), _peer(3, 3, 1)]
    snmp_roles = [
        {"metric": {"cswSwitchNumCurrent": "2"}, "value": [0, "1"]},
        {"metric": {"cswSwitchNumCurrent": "1"}, "value": [0, "2"]},
    ]
    stack = resolve_stack(peers[0], peers, snmp_roles, [], role_slug="access-switch", form_factor="switch-stack")
    assert stack["source"] == "netbox"
    assert [item["number"] for item in stack["members"]] == [1, 3]


def test_snmp_stack_marks_role_and_state():
    roles = [
        {"metric": {"cswSwitchNumCurrent": "1"}, "value": [0, "4"]},
        {"metric": {"cswSwitchNumCurrent": "2"}, "value": [0, "1"]},
    ]
    states = [
        {"metric": {"cswSwitchNumCurrent": "1"}, "value": [0, "4"]},
        {"metric": {"cswSwitchNumCurrent": "2"}, "value": [0, "4"]},
    ]
    stack = stack_from_snmp(roles, states)
    assert stack["source"] == "snmp"
    assert stack["members"][0]["role"] == "standby"
    assert stack["members"][0]["master"] is False
    assert stack["members"][0]["state"] == "ready"
    assert stack["members"][1]["role"] == "active"
    assert stack["members"][1]["master"] is True
    resolved = resolve_stack(
        {"id": "4", "model": "C9300-24P"},
        [],
        roles,
        states,
        role_slug="distribution-switch",
        form_factor="access-switch-24",
    )
    assert resolved == stack | {"members": [
        {**stack["members"][0]},
        {**stack["members"][1]},
    ]}
    assert [item["number"] for item in resolved["members"]] == [1, 2]
    assert resolved["members"][1]["master"] is True


def _members(count, master, state_for=None):
    rows = []
    for number in range(1, count + 1):
        state = "" if state_for is None else state_for(number)
        rows.append({
            "number": number,
            "role": "active" if number == master else "member",
            "model": "",
            "serial": "",
            "state": state,
            "master": number == master,
        })
    return rows


def test_ready_member_is_healthy_and_any_other_state_is_critical():
    members = _members(2, 2, lambda number: "ready" if number == 2 else "verMismatch")
    paint_member_health(members, "warning", "CPU high")
    assert members[0]["health"] == "critical"
    assert members[0]["healthReason"] == "Member state is verMismatch"
    assert members[1]["health"] == "healthy"
    assert members[1]["healthReason"] == "Member state is ready"


def test_device_health_colours_every_tile_when_no_member_was_checked():
    members = _members(3, 1)
    paint_member_health(members, "warning", "CPU high. CPU is above the 80% threshold.")
    assert [item["health"] for item in members] == ["warning", "warning", "warning"]
    assert members[0]["healthReason"] == "CPU high. CPU is above the 80% threshold."


def test_a_member_with_no_sample_is_unknown_when_a_sibling_was_checked():
    members = _members(2, 1, lambda number: "ready" if number == 1 else "")
    paint_member_health(members, "critical", "Device is critical")
    assert members[0]["health"] == "healthy"
    assert members[1]["health"] == "unknown"
    assert members[1]["healthReason"] == "No data pulled from this member"


def test_member_hardware_uses_the_device_thresholds():
    members = _members(4, 1, lambda _number: "ready")
    samples = [
        {"member": member_from_metric({"ciscoEnvMonFanStatusDescr": "Switch 3 Fan 1"}), "kind": "fan", "state": "critical"},
        {"member": 2, "kind": "cpu", "value": 88},
        {"member": 4, "kind": "temp", "value": 76},
        {"member": 1, "kind": "psu", "state": "normal"},
        {"member": None, "kind": "fan", "state": "critical"},
    ]
    paint_member_health(members, "healthy", "Device is healthy", statuses={2: "offline"}, samples=samples)
    assert member_from_metric({"ciscoEnvMonFanStatusDescr": "Switch 3 Fan 1"}) == 3
    assert members[0]["health"] == "healthy"
    assert members[1]["health"] == "critical"
    assert members[1]["healthReason"] == "NetBox status is offline"
    assert members[2]["health"] == "critical"
    assert "Fan degraded" in members[2]["healthReason"]
    assert members[3]["health"] == "critical"
    assert "Temperature high" in members[3]["healthReason"]


def test_cpu_at_88_percent_is_a_warning_on_that_member():
    members = _members(1, 1, lambda _number: "ready")
    paint_member_health(members, "healthy", "Device is healthy", samples=[{"member": 1, "kind": "cpu", "value": 88}])
    assert members[0]["health"] == "warning"
    assert "CPU high" in members[0]["healthReason"]
    assert "80%" in members[0]["healthReason"]


def test_other_devices_have_no_stack():
    assert resolve_stack(
        {"id": "1"}, [], [], [], role_slug="wireless-controller", form_factor="wireless-controller",
    ) is None
    assert resolve_stack(
        {"id": "1"}, [], [], [], role_slug="sdwan", form_factor="firewall",
    ) is None
