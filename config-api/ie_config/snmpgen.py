"""SNMP generator: one-shot binary, MIB uploads, dry-run, diff. Never writes the live snmp.yml."""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timezone

from .storage import atomic_write, unified_diff
from .validators import validate_content

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,120}$")
_EXT = (".mib", ".txt", ".my", ".smi")


def safe_mib_name(name: str) -> str | None:
    if not isinstance(name, str) or not _NAME.match(name):
        return None
    lower = name.lower()
    if not lower.endswith(_EXT):
        return None
    if "/" in name or "\\" in name or ".." in name:
        return None
    return name


def list_mibs(directory: str) -> list[dict]:
    os.makedirs(directory, exist_ok=True)
    out = []
    for name in sorted(os.listdir(directory)):
        if safe_mib_name(name) is None:
            continue
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            modified = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc)
            out.append({
                "name": name,
                "sizeBytes": os.path.getsize(path),
                "uploadedAt": modified.strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
    return out


def save_mib(directory: str, name: str, data: bytes, file_max: int, total_max: int) -> None:
    safe = safe_mib_name(name)
    if safe is None:
        raise ValueError("MIB name must be a single file name ending in .mib, .txt, .my or .smi")
    if len(data) > file_max:
        raise ValueError("MIB file is over the size limit")
    os.makedirs(directory, exist_ok=True)
    total = sum(os.path.getsize(os.path.join(directory, n)) for n in os.listdir(directory)
                if os.path.isfile(os.path.join(directory, n)))
    if total + len(data) > total_max:
        raise ValueError("MIB directory is over the total size limit")
    atomic_write(os.path.join(directory, safe), data, 0o644)


def delete_mib(directory: str, name: str) -> bool:
    safe = safe_mib_name(name)
    if safe is None:
        return False
    path = os.path.realpath(os.path.join(directory, safe))
    root = os.path.realpath(directory)
    if not path.startswith(root + os.sep):
        return False
    if not os.path.isfile(path):
        return False
    os.unlink(path)
    return True


def run_generator(binary: str, generator_yml: str, mib_dir: str, output_path: str, timeout: int = 120) -> tuple[int, str]:
    argv = [binary, "generate", "-g", generator_yml, "-m", mib_dir, "-o", output_path]
    try:
        proc = subprocess.run(argv, capture_output=True, timeout=timeout, check=False, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return 124, "generator timed out"
    except OSError as exc:
        return 127, "generator could not be started: %s" % exc.__class__.__name__
    text = (proc.stdout or b"").decode("utf-8", "replace") + (proc.stderr or b"").decode("utf-8", "replace")
    return proc.returncode, text[-8000:]


def generate(binary: str, generator_yml: str, mib_dir: str, live_snmp: str, work_dir: str) -> dict:
    """Produce a candidate snmp.yml, dry-run it, and diff it against the live file. Does not replace live."""
    os.makedirs(work_dir, exist_ok=True)
    candidate = os.path.join(work_dir, "snmp.yml.candidate")
    if not os.path.isfile(binary):
        return {"ok": False, "message": "snmp generator binary is not in this image (%s)" % binary,
                "output": "", "unified": "", "added": 0, "removed": 0, "content": None}
    code, output = run_generator(binary, generator_yml, mib_dir, candidate)
    if code != 0 or not os.path.isfile(candidate):
        return {"ok": False, "message": "generator failed", "output": output, "unified": "", "added": 0,
                "removed": 0, "content": None}
    with open(candidate, "r", encoding="utf-8", errors="replace") as fh:
        content = fh.read()
    dry = validate_content("snmp", "yaml", content)
    live = ""
    if os.path.isfile(live_snmp):
        with open(live_snmp, "r", encoding="utf-8", errors="replace") as fh:
            live = fh.read()
    diff = unified_diff(live, content, "snmp.yml")
    ok = bool(dry["ok"])
    message = "candidate ready; dry-run passed" if ok else "candidate produced but snmp_exporter dry-run failed"
    return {
        "ok": ok,
        "message": message + ". The live snmp.yml was not changed; save it with PUT if you want to apply it.",
        "output": output,
        "tool": dry["tool"],
        "messages": dry["messages"],
        "unified": diff["unified"],
        "added": diff["added"],
        "removed": diff["removed"],
        "content": content,
    }
