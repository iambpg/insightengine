"""Atomic writes, etags, unified diffs and backup history."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone

from .registry import FileSpec, Registry


def etag_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_bytes(path: str) -> bytes | None:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def atomic_write(path: str, data: bytes, mode: int = 0o644) -> None:
    """Write to a temp file in the same directory, fsync, then rename over the target."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".ie-tmp-", dir=directory)
    try:
        os.write(fd, data)
        os.fsync(fd)
        os.fchmod(fd, mode)
        os.close(fd)
        fd = -1
        os.replace(tmp, path)
        # Best-effort directory fsync so the rename itself is durable.
        try:
            dfd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass
    finally:
        if fd >= 0:
            os.close(fd)
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def unified_diff(old: str, new: str, path: str) -> dict:
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = "".join(difflib.unified_diff(old_lines, new_lines, fromfile=path, tofile=path + " (editor)"))
    added = removed = 0
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return {"unified": diff, "added": added, "removed": removed}


def _history_dir(root: str, app: str, file_id: str) -> str:
    return os.path.join(root, app, file_id)


def backup(history_root: str, app: str, file_id: str, content: bytes, user: str, comment: str,
           keep: int, days: int) -> str:
    os.makedirs(_history_dir(history_root, app, file_id), exist_ok=True)
    hid = "%s-%s" % (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"), hashlib.sha256(content).hexdigest()[:8])
    rec = {
        "id": hid,
        "savedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "user": user,
        "comment": comment[:500],
        "sizeBytes": len(content),
        "content": content.decode("utf-8", "replace"),
    }
    path = os.path.join(_history_dir(history_root, app, file_id), hid + ".json")
    atomic_write(path, json.dumps(rec).encode("utf-8"), 0o600)
    prune(history_root, app, file_id, keep, days)
    return hid


def list_history(history_root: str, app: str, file_id: str) -> list[dict]:
    d = _history_dir(history_root, app, file_id)
    out = []
    if not os.path.isdir(d):
        return out
    for name in os.listdir(d):
        if not name.endswith(".json"):
            continue
        rec = _read_rec(os.path.join(d, name))
        if rec:
            out.append({k: rec[k] for k in ("id", "savedAt", "user", "comment", "sizeBytes")})
    out.sort(key=lambda r: r["savedAt"], reverse=True)
    return out


def get_history(history_root: str, app: str, file_id: str, hid: str) -> dict | None:
    if not re_safe_id(hid):
        return None
    path = os.path.join(_history_dir(history_root, app, file_id), hid + ".json")
    # stay inside the history directory
    real = os.path.realpath(path)
    base = os.path.realpath(_history_dir(history_root, app, file_id))
    if not real.startswith(base + os.sep):
        return None
    return _read_rec(real)


def re_safe_id(hid: str) -> bool:
    return bool(hid) and "/" not in hid and ".." not in hid and len(hid) < 80 and all(c.isalnum() or c in "-T:Z" or c == "T" for c in hid)


def _read_rec(path: str) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            rec = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(rec, dict) or "content" not in rec:
        return None
    return rec


def prune(history_root: str, app: str, file_id: str, keep: int, days: int) -> None:
    d = _history_dir(history_root, app, file_id)
    if not os.path.isdir(d):
        return
    files = []
    for name in os.listdir(d):
        if name.endswith(".json"):
            p = os.path.join(d, name)
            try:
                files.append((os.path.getmtime(p), p))
            except OSError:
                continue
    files.sort(reverse=True)  # newest first
    cutoff = time.time() - days * 86400
    for i, (mtime, path) in enumerate(files):
        if i < keep or mtime >= cutoff:
            continue
        try:
            os.unlink(path)
        except OSError:
            pass


def file_stat(reg: Registry, spec: FileSpec) -> tuple[str | None, int, str | None]:
    """Return (absolute path or None, size, iso mtime). Missing file -> size 0."""
    try:
        path = reg.resolve(spec)
    except ValueError:
        return None, 0, None
    try:
        st = os.stat(path)
    except OSError:
        return path, 0, None
    mtime = datetime.fromtimestamp(st.st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return path, st.st_size, mtime


def too_old_cutoff(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)
