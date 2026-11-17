"""Device login accounts used by config backup.

Several logins can be saved without choosing a device. A config pull tries
them on each device that does not already have a login that worked. The one
that signs in is used again the next time that device is pulled. Passwords
are never returned by the API.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import re
import secrets
import socket
import threading
import uuid
from urllib.parse import quote

from .errors import ApiError

log = logging.getLogger("ie-config.device-logins")

_MAX_ACCOUNTS = 50
_file_lock = threading.Lock()
_probe_lock = threading.Lock()
_probe = {"running": False, "again": False, "nodes": []}


def logins_path(settings) -> str:
    root = getattr(settings, "config_root", "") or ""
    return os.path.join(root, "data", "vault", "device-logins.json")


def token_path(settings) -> str:
    root = getattr(settings, "config_root", "") or ""
    return os.path.join(root, "data", "vault", "oxidized-source.token")


def _read_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            body = json.load(handle)
    except (OSError, ValueError):
        return {"accounts": []}
    if not isinstance(body, dict):
        return {"accounts": []}
    accounts = body.get("accounts")
    if not isinstance(accounts, list):
        body["accounts"] = []
    return body


def _write_json(path: str, body: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    raw = (json.dumps(body, indent=2) + "\n").encode("utf-8")
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def _clean_text(value, label: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ApiError(400, "bad_value", "%s is required" % label)
    text = value.strip()
    if not text:
        raise ApiError(400, "bad_value", "%s is required" % label)
    if len(text) > limit or any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise ApiError(400, "bad_value", "%s is not valid" % label)
    return text


def load_store(settings) -> dict:
    with _file_lock:
        return _read_json(logins_path(settings))


def load_accounts(settings) -> list[dict]:
    stored = load_store(settings).get("accounts") or []
    return [row for row in stored if isinstance(row, dict)]


def _worked_id(worked: dict, hostname: str) -> str:
    wanted = (hostname or "").strip().lower()
    if not wanted or not isinstance(worked, dict):
        return ""
    for name, account_id in worked.items():
        if str(name).strip().lower() == wanted:
            return str(account_id or "")
    return ""


def public_accounts(settings) -> list[dict]:
    stored = load_store(settings)
    worked = stored.get("worked") if isinstance(stored.get("worked"), dict) else {}
    used: dict[str, list[str]] = {}
    for name, account_id in worked.items():
        used.setdefault(str(account_id or ""), []).append(str(name))
    shown = []
    for row in stored.get("accounts") or []:
        if not isinstance(row, dict):
            continue
        account_id = str(row.get("id") or "")
        shown.append({
            "id": account_id,
            "label": str(row.get("label") or ""),
            "username": str(row.get("username") or ""),
            "passwordSet": bool(str(row.get("password") or "")),
            "workedOn": sorted(used.get(account_id) or []),
        })
    return shown


def credential_for(accounts: list[dict], hostname: str, worked: dict | None = None) -> tuple[str, str] | None:
    """Login that signed in to this device last time, if that login still exists."""
    account_id = _worked_id(worked or {}, hostname)
    if not account_id:
        return None
    for row in accounts:
        if str(row.get("id") or "") != account_id:
            continue
        username = str(row.get("username") or "")
        password = str(row.get("password") or "")
        if username and password:
            return username, password
    return None


def save_account(settings, body: dict) -> dict:
    if not isinstance(body, dict):
        raise ApiError(400, "bad_body", "body must be a JSON object")
    label = _clean_text(body.get("label"), "account name", 80)
    username = _clean_text(body.get("username"), "username", 128)
    wanted_id = str(body.get("id") or "").strip()
    password = body.get("password")
    if password is None:
        password = ""
    if not isinstance(password, str):
        raise ApiError(400, "bad_value", "password is not valid")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in password) or len(password) > 256:
        raise ApiError(400, "bad_value", "password is not valid")

    with _file_lock:
        stored = _read_json(logins_path(settings))
        return _save_locked(stored, settings, label, username, password, wanted_id)


def _save_locked(stored, settings, label, username, password, wanted_id) -> dict:
    accounts = [row for row in (stored.get("accounts") or []) if isinstance(row, dict)]
    current = None
    if wanted_id:
        for row in accounts:
            if str(row.get("id") or "") == wanted_id:
                current = row
                break
        if current is None:
            raise ApiError(404, "not_found", "unknown device login")
    if not password:
        if current is None:
            raise ApiError(400, "bad_value", "password is required")
        password = str(current.get("password") or "")
        if not password:
            raise ApiError(400, "bad_value", "password is required")

    if current is None:
        if len(accounts) >= _MAX_ACCOUNTS:
            raise ApiError(400, "bad_value", "too many device logins")
        current = {"id": uuid.uuid4().hex}
        accounts.append(current)
    elif str(current.get("username") or "") != username:
        worked = stored.get("worked") if isinstance(stored.get("worked"), dict) else {}
        stored["worked"] = {
            name: found for name, found in worked.items() if str(found) != str(current.get("id") or "")
        }
    current["label"] = label
    current["username"] = username
    current["password"] = password
    current.pop("devices", None)
    stored["accounts"] = accounts
    stored["generation"] = int(stored.get("generation") or 0) + 1
    _write_json(logins_path(settings), stored)
    return {
        "id": current["id"],
        "label": label,
        "username": username,
        "passwordSet": True,
        "workedOn": _names_for(stored, current["id"]),
    }


def delete_account(settings, account_id: str) -> None:
    wanted = (account_id or "").strip()
    with _file_lock:
        stored = _read_json(logins_path(settings))
        accounts = [row for row in (stored.get("accounts") or []) if isinstance(row, dict)]
        kept = [row for row in accounts if str(row.get("id") or "") != wanted]
        if len(kept) == len(accounts):
            raise ApiError(404, "not_found", "unknown device login")
        worked = stored.get("worked") if isinstance(stored.get("worked"), dict) else {}
        stored["accounts"] = kept
        stored["worked"] = {name: found for name, found in worked.items() if str(found) != wanted}
        stored["generation"] = int(stored.get("generation") or 0) + 1
        _write_json(logins_path(settings), stored)


def ensure_source_token(settings) -> str:
    path = token_path(settings)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            current = handle.read().strip()
    except OSError:
        current = ""
    if current and re.fullmatch(r"[A-Za-z0-9_-]{16,128}", current):
        return current
    current = secrets.token_urlsafe(32)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, (current + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(path, 0o600)
    return current


def _names_for(stored: dict, account_id: str) -> list[str]:
    worked = stored.get("worked") if isinstance(stored.get("worked"), dict) else {}
    return sorted(str(name) for name, found in worked.items() if str(found) == account_id)


def ssh_login(ip: str, username: str, password: str) -> str:
    """One SSH sign-in. ok, auth (rejected), or down (device did not answer)."""
    import paramiko
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            ip, port=22, username=username, password=password,
            timeout=5, auth_timeout=10, banner_timeout=10,
            look_for_keys=False, allow_agent=False,
        )
        return "ok"
    except paramiko.AuthenticationException:
        return "auth"
    except paramiko.ssh_exception.NoValidConnectionsError:
        return "down"
    except (socket.timeout, TimeoutError, ConnectionRefusedError, ConnectionResetError, OSError):
        return "down"
    except paramiko.SSHException:
        return "auth"
    finally:
        try:
            client.close()
        except Exception:
            pass


def match_devices(settings, nodes: list[dict], try_login=ssh_login) -> list[str]:
    """Try saved logins on devices that do not yet have one that worked.

    A device that already signed in keeps that login. The first login that
    signs in is stored and returned so the config pull can use it.
    """
    with _file_lock:
        stored = _read_json(logins_path(settings))
        accounts = [row for row in (stored.get("accounts") or []) if isinstance(row, dict)]
        worked = dict(stored.get("worked") or {}) if isinstance(stored.get("worked"), dict) else {}
    if not accounts:
        return []
    newly = []
    learned = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        name = str(node.get("name") or "").strip()
        ip = str(node.get("ip") or "").split("/")[0].strip()
        if not name or not ip:
            continue
        if credential_for(accounts, name, worked):
            continue
        for row in accounts:
            username = str(row.get("username") or "")
            password = str(row.get("password") or "")
            if not username or not password:
                continue
            try:
                result = try_login(ip, username, password)
            except Exception:
                log.warning("device login check failed for %s", name)
                result = "down"
            if result == "ok":
                learned[name] = str(row.get("id") or "")
                newly.append(name)
                log.info("device login matched %s with %s", name, row.get("label") or row.get("username"))
                break
            if result == "down":
                log.info("device login check skipped %s because SSH did not answer", name)
                break
    if not learned:
        return []
    with _file_lock:
        stored = _read_json(logins_path(settings))
        current = dict(stored.get("worked") or {}) if isinstance(stored.get("worked"), dict) else {}
        for name, account_id in learned.items():
            current = {key: value for key, value in current.items() if str(key).lower() != name.lower()}
            current[name] = account_id
        stored["worked"] = current
        _write_json(logins_path(settings), stored)
    return newly


def schedule_probe(settings, nodes: list[dict]) -> None:
    """Try logins in the background, then queue a config pull for new matches."""
    usable = []
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        name = str(node.get("name") or "").strip()
        ip = str(node.get("ip") or "").split("/")[0].strip()
        if name and ip:
            usable.append({"name": name, "ip": ip})
    if not usable:
        return
    with _probe_lock:
        _probe["nodes"] = usable
        if _probe["running"]:
            _probe["again"] = True
            return
        _probe["running"] = True
    threading.Thread(target=_probe_loop, args=(settings,), name="device-logins", daemon=True).start()


def _probe_loop(settings) -> None:
    while True:
        with _probe_lock:
            nodes = list(_probe["nodes"])
            _probe["again"] = False
        try:
            learned = match_devices(settings, nodes)
        except Exception:
            log.warning("device login check could not finish")
            learned = []
        if learned:
            _queue_pull(settings, learned)
        with _probe_lock:
            if not _probe["again"]:
                _probe["running"] = False
                return


def _queue_pull(settings, names: list[str]) -> None:
    import httpx
    base = (getattr(settings, "oxidized_url", "") or "http://oxidized:8888").rstrip("/")
    try:
        httpx.get(base + "/reload", timeout=10.0)
    except httpx.HTTPError:
        log.warning("Oxidized did not reload after a device login matched")
        return
    for name in names:
        try:
            httpx.get(base + "/node/next/" + quote(name, safe="") + ".json", timeout=10.0)
        except httpx.HTTPError:
            log.warning("config pull was not queued for %s", name)


def source_token_matches(settings, presented: str) -> bool:
    expected = ensure_source_token(settings)
    offered = presented or ""
    if not isinstance(offered, str):
        return False
    return hmac.compare_digest(offered.strip(), expected)
