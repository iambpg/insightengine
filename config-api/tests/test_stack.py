"""Stack badge: NetBox chassis, then stackwise, then a single tile."""

from ie_config.stack import resolve_stack, stack_from_snmp


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


def test_other_devices_have_no_stack():
    assert resolve_stack(
        {"id": "1"}, [], [], [], role_slug="wireless-controller", form_factor="wireless-controller",
    ) is None
    assert resolve_stack(
        {"id": "1"}, [], [], [], role_slug="sdwan", form_factor="firewall",
    ) is None
