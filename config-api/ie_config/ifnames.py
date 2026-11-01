"""Canonical interface names for joining NetBox, Netdisco and SNMP.

Cisco (and similar) inventories use the long name while IF-MIB ifName is the
short form. FastEthernet0/21 and Fa0/21 are the same port. Matching is
case-insensitive and also accepts ifDescr and ifAlias.
"""

from __future__ import annotations

import re

# Longest prefix is tried first. A short prefix only matches when the rest is
# empty or starts with a digit, slash or dot, so FortiGate "port1" is not "po".
_PREFIXES: tuple[tuple[str, str], ...] = (
    ("fortygigabitethernet", "fo"),
    ("hundredgigabitethernet", "hu"),
    ("twentyfivegigabitethernet", "twe"),
    ("tengigabitethernet", "te"),
    ("gigabitethernet", "gi"),
    ("fastethernet", "fa"),
    ("twentyfivegige", "twe"),
    ("tengigethernet", "te"),
    ("fortygige", "fo"),
    ("hundredgige", "hu"),
    ("portchannel", "po"),
    ("management", "mgmt"),
    ("fortilink", "fortilink"),
    ("ethernet", "eth"),
    ("loopback", "lo"),
    ("tunnel", "tu"),
    ("vlan", "vl"),
    ("twe", "twe"),
    ("mgmt", "mgmt"),
    ("eth", "eth"),
    ("ae", "ae"),
    ("fa", "fa"),
    ("gi", "gi"),
    ("te", "te"),
    ("fo", "fo"),
    ("hu", "hu"),
    ("et", "eth"),
    ("po", "po"),
    ("vl", "vl"),
    ("lo", "lo"),
    ("tu", "tu"),
    ("ma", "mgmt"),
)
_SORTED = tuple(sorted(_PREFIXES, key=lambda item: len(item[0]), reverse=True))
_GUARDED = {prefix for prefix, _short in _PREFIXES if len(prefix) <= 4}


def iface_compact(name: str) -> str:
    return re.sub(r"[\s_\-]+", "", (name or "").strip().lower())


def canonical_iface(name: str) -> str:
    """One key for long and short forms of the same interface."""
    compact = iface_compact(name)
    if not compact:
        return ""
    for prefix, short in _SORTED:
        if compact != prefix and not compact.startswith(prefix):
            continue
        rest = compact[len(prefix):]
        if prefix in _GUARDED and rest and rest[0] not in "0123456789./":
            continue
        return short + rest
    return compact


def iface_match_keys(name: str) -> set[str]:
    """Every string that should hit this interface in a join."""
    raw = (name or "").strip()
    if not raw:
        return set()
    keys = {raw.lower(), iface_compact(raw), canonical_iface(raw)}
    return {key for key in keys if key}


def names_match(left: str, right: str) -> bool:
    return bool(iface_match_keys(left) & iface_match_keys(right))
