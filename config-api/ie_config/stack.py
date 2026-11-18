"""Stack-badge members for a switch.

The member number is the chassis number the faceplate already uses
(GigabitEthernet2/0/1 is member 2). NetBox vc_position and
cswSwitchNumCurrent are that same number. Nothing here renumbers them.

NetBox virtual chassis wins. virtual_chassis.master is the active member.
With no chassis, CISCO-STACKWISE-MIB samples from Prometheus are used.
With neither, the switch is one tile numbered 1. A collector that has no
stack fields (including a Zabbix-only install) takes that same fallback.
"""

from __future__ import annotations

SWITCH_FORMS = {"access-switch-24", "access-switch-48", "switch-stack"}

# CISCO-STACKWISE-MIB cswSwitchRole: master(1), member(2), notMember(3), standby(4).
_ROLE = {1: "active", 2: "member", 3: "member", 4: "standby"}

# cswSwitchState.
_STATE = {
    1: "waiting",
    2: "progressing",
    3: "added",
    4: "ready",
    5: "sdmMismatch",
    6: "verMismatch",
    7: "featureMismatch",
    8: "newMasterInit",
    9: "provisioned",
    10: "invalid",
    11: "removed",
}


def is_switch(role_slug: str, form_factor: str) -> bool:
    if (form_factor or "").strip() in SWITCH_FORMS:
        return True
    return "switch" in (role_slug or "").lower()


def _member(number: int, role: str, model: str = "", serial: str = "", state: str = "", master: bool = False) -> dict:
    return {
        "number": int(number),
        "role": role or "member",
        "model": model or "",
        "serial": serial or "",
        "state": state or "",
        "master": bool(master),
    }


def standalone_stack(model: str = "", serial: str = "") -> dict:
    return {"source": "standalone", "members": [_member(1, "active", model, serial, "", True)]}


def _position(raw) -> int | None:
    try:
        number = int(raw)
    except (TypeError, ValueError):
        return None
    if number < 1:
        return None
    return number


def stack_from_netbox(device: dict, peers: list[dict]) -> dict | None:
    """Members of this device's virtual chassis. None when it has no chassis."""
    device = device or {}
    vc_id = str(device.get("vc_id") or "").strip()
    if not vc_id:
        return None
    grouped = [peer for peer in peers or [] if str(peer.get("vc_id") or "").strip() == vc_id]
    if not any(peer is device or str(peer.get("id") or "") == str(device.get("id") or "") for peer in grouped):
        grouped.append(device)
    master_id = ""
    for peer in grouped:
        master_id = str(peer.get("vc_master_id") or "").strip()
        if master_id:
            break
    members = []
    seen: set[int] = set()
    for peer in grouped:
        number = _position(peer.get("vc_position"))
        if number is None or number in seen:
            continue
        seen.add(number)
        is_master = bool(master_id) and str(peer.get("id") or "") == master_id
        members.append(_member(
            number,
            "active" if is_master else "member",
            str(peer.get("model") or ""),
            str(peer.get("serial") or ""),
            "",
            is_master,
        ))
    members.sort(key=lambda item: item["number"])
    if not members:
        return standalone_stack(str(device.get("model") or ""), str(device.get("serial") or ""))
    return {"source": "netbox", "members": members}


def _sample_number(metric: dict) -> int | None:
    return _position(metric.get("cswSwitchNumCurrent"))


def _sample_value(sample: dict) -> int | None:
    value = sample.get("value") if isinstance(sample, dict) else None
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        return int(float(value[1]))
    except (TypeError, ValueError):
        return None


def stack_from_snmp(role_samples, state_samples) -> dict | None:
    """One member per cswSwitchNumCurrent. Role 1 is the active master."""
    roles: dict[int, int] = {}
    states: dict[int, int] = {}
    for sample in role_samples or []:
        if not isinstance(sample, dict):
            continue
        metric = sample.get("metric") if isinstance(sample.get("metric"), dict) else {}
        number = _sample_number(metric)
        value = _sample_value(sample)
        if number is None or value is None:
            continue
        roles[number] = value
    for sample in state_samples or []:
        if not isinstance(sample, dict):
            continue
        metric = sample.get("metric") if isinstance(sample.get("metric"), dict) else {}
        number = _sample_number(metric)
        value = _sample_value(sample)
        if number is None or value is None:
            continue
        states[number] = value
    if not roles and not states:
        return None
    members = []
    for number in sorted(set(roles) | set(states)):
        role = _ROLE.get(roles.get(number), "member")
        members.append(_member(number, role, "", "", _STATE.get(states.get(number), ""), role == "active"))
    return {"source": "snmp", "members": members}


def resolve_stack(
    device: dict,
    peers: list[dict],
    role_samples=None,
    state_samples=None,
    *,
    role_slug: str = "",
    form_factor: str = "",
) -> dict | None:
    if not is_switch(role_slug, form_factor):
        return None
    device = device or {}
    if str(device.get("vc_id") or "").strip():
        return stack_from_netbox(device, peers)
    snmp = stack_from_snmp(role_samples, state_samples)
    if snmp is not None:
        return snmp
    return standalone_stack(str(device.get("model") or ""), str(device.get("serial") or ""))
