"""Mask secret-looking values inside editable files. Secret files are never read by this module."""

from __future__ import annotations

import re

# Keys whose values are secrets. "pass" covers Netdisco auth/priv pass fields.
_KEY = re.compile(
    r"^(password|secret|token|community|api_key|apikey|priv_password|priv_pass|"
    r"auth_password|credential|credentials|bearer|passwd|pass)$",
    re.I,
)
_LINE = re.compile(
    r"^(?P<prefix>\s*(?:[\"']?)(?P<key>[A-Za-z0-9_.-]+)(?:[\"']?)\s*[:=]\s*)(?P<val>\S.*?)\s*$"
)
_PLACEHOLDER_VALUE = re.compile(r"""^["']?\$\{[A-Z0-9_]+\}["']?$""")
_ENV_REF = re.compile(r"""^["']?@@[A-Z0-9_]+@@["']?$""")


def _is_reference(val: str) -> bool:
    v = val.strip().strip(",").rstrip(",")
    return bool(_PLACEHOLDER_VALUE.match(v) or _ENV_REF.match(v) or v in ("|", ">", "|-", ">-"))


def slots(text: str) -> list[dict]:
    """Ordered secret slots. placeholder -> original raw value token (quotes included)."""
    found: list[dict] = []
    counts: dict[str, int] = {}
    for line in text.splitlines():
        m = _LINE.match(line)
        if not m or not _KEY.match(m.group("key")):
            continue
        val = m.group("val")
        if not val or _is_reference(val) or val.startswith("__SECRET__:") or val.startswith('"__SECRET__:'):
            continue
        key = m.group("key")
        counts[key] = counts.get(key, 0) + 1
        name = key if counts[key] == 1 else "%s#%d" % (key, counts[key])
        found.append({"name": name, "key": key, "token": val, "placeholder": '"__SECRET__:%s"' % name})
    return found


def mask_text(text: str) -> tuple[str, list[str]]:
    out_lines = []
    keys: list[str] = []
    counts: dict[str, int] = {}
    for line in text.splitlines(keepends=True):
        body = line[:-1] if line.endswith("\n") else line
        nl = "\n" if line.endswith("\n") else ""
        m = _LINE.match(body)
        if not m or not _KEY.match(m.group("key")) or _is_reference(m.group("val")):
            out_lines.append(line)
            continue
        val = m.group("val")
        if not val or val.startswith("__SECRET__:") or val.startswith('"__SECRET__:'):
            out_lines.append(line)
            continue
        key = m.group("key")
        counts[key] = counts.get(key, 0) + 1
        name = key if counts[key] == 1 else "%s#%d" % (key, counts[key])
        keys.append(name)
        new_body = body[: m.start("val")] + ('"__SECRET__:%s"' % name) + body[m.end("val"):]
        out_lines.append(new_body + nl)
    return "".join(out_lines), keys


def restore_secrets(new_text: str, old_text: str) -> str:
    """Put original secret tokens back wherever the editor kept a placeholder."""
    restored = new_text
    # Longer names first so password#2 is not partially eaten by password.
    for slot in sorted(slots(old_text), key=lambda s: len(s["name"]), reverse=True):
        restored = restored.replace(slot["placeholder"], slot["token"])
        restored = restored.replace("__SECRET__:%s" % slot["name"], slot["token"])
    return restored


def leftover_placeholders(text: str) -> list[str]:
    return re.findall(r"__SECRET__:[A-Za-z0-9_#.-]+", text)
