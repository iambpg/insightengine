"""Strip a configured DNS suffix from device names.

HOSTNAME_STRIP_SUFFIXES is comma-separated. The default is empty: a suffix
such as .pnp.co.za belongs to one network, not to InsightEngine. The same
list is written into Netdisco's domain_suffix so its own UI shortens names.
sync.yml hostname_strip_suffixes is used when the environment variable is empty,
so Settings → Netdisco can set it without a restart of the variable.
"""

from __future__ import annotations

import os
import re

_PAREN = re.compile(r"\s*\([^)]*\)\s*$")


def parse_suffixes(raw) -> list[str]:
    """Normalise a comma-separated string or a list. Leading dots are added."""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        parts = [str(item) for item in raw]
    else:
        parts = str(raw).split(",")
    found: list[str] = []
    for part in parts:
        text = part.strip().lower()
        if not text:
            continue
        if not text.startswith("."):
            text = "." + text
        if text not in found:
            found.append(text)
    return found


def _longest(suffixes: list[str]) -> list[str]:
    return sorted(suffixes, key=len, reverse=True)


def strip_suffix(value: str, suffixes: list[str] | None) -> str:
    """Remove one configured suffix from the end. The rest of the name is kept."""
    text = (value or "").strip()
    if not text or not suffixes:
        return text
    lowered = text.lower()
    for suffix in _longest(list(suffixes)):
        if lowered.endswith(suffix) and len(text) > len(suffix):
            return text[: len(text) - len(suffix)].rstrip(".")
    return text


def strip_hostname(value: str, suffixes: list[str] | None = None) -> str:
    """Short name for display and for NetBox. Suffix only, original case kept."""
    return strip_suffix(value, suffixes)


def strip_device_label(value: str, suffixes: list[str] | None = None) -> str:
    """CDP/LLDP device id: drop a trailing '(SERIAL)' and the domain suffix.

    cdpCacheDeviceId is often 'host.example.com (FOC1234)' or the serial in
    parentheses after the FQDN. The parenthetical is removed from the end only.
    """
    text = (value or "").strip()
    if not text:
        return ""
    text = _PAREN.sub("", text).strip()
    text = strip_suffix(text, suffixes)
    text = _PAREN.sub("", text).strip()
    return strip_suffix(text, suffixes)


def names_match(left: str, right: str, suffixes: list[str] | None = None) -> bool:
    """True when two device names are equal after suffix stripping."""
    a = (left or "").strip().lower()
    b = (right or "").strip().lower()
    if not a or not b:
        return False
    if a == b:
        return True
    if not suffixes:
        return False
    return strip_suffix(a, suffixes).lower() == strip_suffix(b, suffixes).lower()


def suffix_pattern(suffixes: list[str] | None) -> str:
    """PostgreSQL regex that matches one configured suffix at the end of a name."""
    parts = [re.escape(suffix) for suffix in _longest(list(suffixes or [])) if suffix]
    if not parts:
        return ""
    return "(?:" + "|".join(parts) + ")$"


def domain_suffix_yaml(suffixes: list[str] | None) -> str:
    """Netdisco domain_suffix block. Empty when nothing is configured."""
    items = list(suffixes or [])
    if not items:
        return ""
    lines = [
        "# Hostnames with these suffixes are shown without them.",
        "# Same list as HOSTNAME_STRIP_SUFFIXES, or sync.yml hostname_strip_suffixes.",
        "domain_suffix:",
    ]
    for suffix in items:
        lines.append("  - '%s'" % suffix.replace("'", "''"))
    return "\n".join(lines) + "\n\n"


def inject_domain_suffix(rendered: str, suffixes: list[str] | None) -> str:
    block = domain_suffix_yaml(suffixes)
    if not block:
        return rendered
    return block + rendered


def effective_suffixes(settings, sync: dict | None = None) -> list[str]:
    """Environment wins. Otherwise the Netdisco sync.yml list."""
    env_raw = getattr(settings, "hostname_strip_suffixes", "") or ""
    if not str(env_raw).strip():
        env_raw = os.environ.get("HOSTNAME_STRIP_SUFFIXES", "")
    from_env = parse_suffixes(env_raw)
    if from_env:
        return from_env
    data = sync
    if data is None:
        data = _read_sync(getattr(settings, "config_root", "") or "")
    if not isinstance(data, dict):
        return []
    return parse_suffixes(data.get("hostname_strip_suffixes"))


def _read_sync(root: str) -> dict:
    if not root:
        return {}
    path = os.path.join(root, "config", "discovery", "sync.yml")
    if not os.path.isfile(path):
        return {}
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
    except (OSError, ValueError):
        return {}
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}
