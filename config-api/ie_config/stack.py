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

import re

from .health import explain_health

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


# Same ranking as explain_health. unknown is a tile with nothing of its own.
_TILE_RANK = {"unknown": -1, "healthy": 0, "warning": 1, "critical": 2, "unreachable": 3}
_NETBOX_DOWN = {"offline", "failed", "decommissioning"}
_MEMBER_TEXT = re.compile(r"(?i)(?:switch|member)\s*#?\s*(\d{1,2})\b|\bsw(\d{1,2})\b")


def member_from_metric(metric: dict) -> int | None:
    """Stack member named by a sensor label, such as 'Switch 2 Fan 1'."""
    if not isinstance(metric, dict):
        return None
    for key in ("cswSwitchNumCurrent", "member", "stack_member"):
        number = _position(metric.get(key))
        if number is not None:
            return number
    for key, value in metric.items():
        if key == "__name__" or value is None:
            continue
        match = _MEMBER_TEXT.search(str(value))
        if not match:
            continue
        raw = match.group(1) or match.group(2)
        number = _position(raw)
        if number is not None:
            return number
    return None


def _sensor_snapshot(samples: list[dict]) -> dict:
    fans, psus, cpus, temps, memories = [], [], [], [], []
    for sample in samples:
        kind = sample.get("kind")
        if kind == "fan" and sample.get("state"):
            fans.append(sample["state"])
        elif kind == "psu" and sample.get("state"):
            psus.append(sample["state"])
        elif kind == "cpu" and sample.get("value") is not None:
            cpus.append(sample["value"])
        elif kind == "temp" and sample.get("value") is not None:
            temps.append(sample["value"])
        elif kind == "memory" and sample.get("value") is not None:
            memories.append(sample["value"])
    snap = {}
    if fans:
        snap["fans"] = fans
    if psus:
        snap["psus"] = psus
    if cpus:
        snap["cpu"] = max(cpus)
    if temps:
        snap["tempC"] = max(temps)
    if memories:
        snap["memoryPercent"] = max(memories)
    return snap


def _worst_item_reason(items: list[dict]) -> str:
    best = None
    best_rank = -1
    for item in items or []:
        effect = str(item.get("effect") or item.get("severity") or "")
        rank = _TILE_RANK.get(effect, 0)
        if rank > best_rank and rank > 0:
            best = item
            best_rank = rank
    if not best:
        return ""
    title = str(best.get("title") or "").strip()
    detail = str(best.get("detail") or "").strip()
    if title and detail:
        return "%s. %s" % (title, detail)
    return title or detail


def paint_member_health(
    members: list[dict],
    device_health: str,
    device_reason: str = "",
    statuses: dict | None = None,
    samples: list[dict] | None = None,
) -> list[dict]:
    """Colour each tile from that member's own signals.

    Stackwise state, a down NetBox status, and PSU, fan, temperature, CPU
    and memory samples that name the member use the same thresholds as the
    device badge. A state other than ready is critical. When no member has
    any of those signals, every tile uses the device health. A member with
    nothing of its own, beside members that do, is unknown.
    """
    statuses = statuses or {}
    grouped: dict[int, list[dict]] = {}
    for sample in samples or []:
        if not isinstance(sample, dict):
            continue
        number = sample.get("member")
        if not isinstance(number, int):
            continue
        grouped.setdefault(number, []).append(sample)
    own: dict[int, list[tuple[int, str]]] = {}
    for member in members or []:
        number = member.get("number")
        signals: list[tuple[int, str]] = []
        state = str(member.get("state") or "").strip()
        if state:
            if state.lower() == "ready":
                signals.append((0, "Member state is ready"))
            else:
                signals.append((2, "Member state is %s" % state))
        status = str(statuses.get(number) or "").strip().lower()
        if status in _NETBOX_DOWN:
            signals.append((2, "NetBox status is %s" % status))
        snap = _sensor_snapshot(grouped.get(number) or [])
        if snap:
            explained = explain_health(snap)
            effect = explained.get("health") or "healthy"
            reason = _worst_item_reason(explained.get("items") or [])
            if not reason:
                reason = "Within the device health thresholds"
            signals.append((_TILE_RANK.get(effect, 0), reason))
        own[number] = signals
    any_own = any(own.values())
    fallback = device_health if device_health in _TILE_RANK and device_health != "unknown" else "unknown"
    for member in members or []:
        signals = own.get(member.get("number")) or []
        if not signals:
            if not any_own:
                member["health"] = fallback
                member["healthReason"] = device_reason or "Device is %s" % fallback
            else:
                member["health"] = "unknown"
                member["healthReason"] = "No data pulled from this member"
            continue
        rank = max(score for score, _text in signals)
        health = next(name for name, score in _TILE_RANK.items() if score == rank)
        if health == "healthy":
            ready = next((text for score, text in signals if score == 0 and text.startswith("Member state")), "")
            member["healthReason"] = ready or "Within the device health thresholds"
        else:
            member["healthReason"] = "; ".join(text for score, text in signals if score == rank)
        member["health"] = health
    return members
