"""Read-only device CLI.

Commands are an exact allowlist per platform. The password is read from a
file under the secrets directory and is never returned, logged, or audited.
"""

from __future__ import annotations

import json
import os
import re
import time
from urllib.parse import unquote

from fastapi import Request

from .errors import ApiError
from .fleet import FleetService

CLI_ROLES = {"Administrator", "Engineer"}
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_FORBIDDEN = (";", "|", "&", "`", "$(", ">", "<", "\n", "\r")
_OUTPUT_LIMIT = 48000

# Canonical command text is what is sent. Lookup is case-insensitive.
_IOS = (
    ("System", "version", "Show version", "show version"),
    ("System", "inventory", "Show inventory", "show inventory"),
    ("System", "environment", "Show environment", "show environment all"),
    ("System", "cpu", "CPU", "show processes cpu"),
    ("System", "memory", "Memory", "show processes memory"),
    ("System", "logging", "Show logging", "show logging"),
    ("Interfaces", "brief", "Interface summary", "show ip interface brief"),
    ("Interfaces", "status", "Interface status", "show interfaces status"),
    ("Interfaces", "errors", "Interface errors", "show interfaces counters errors"),
    ("Interfaces", "poe", "PoE", "show power inline"),
    ("Layer 2 and 3", "vlan", "VLANs", "show vlan brief"),
    ("Layer 2 and 3", "mac", "MAC table", "show mac address-table"),
    ("Layer 2 and 3", "stp", "Spanning tree", "show spanning-tree summary"),
    ("Layer 2 and 3", "route", "Routing table", "show ip route"),
    ("Layer 2 and 3", "lldp", "LLDP neighbors", "show lldp neighbors"),
    ("System", "clock", "Clock", "show clock"),
)
_NXOS = (
    ("System", "version", "Show version", "show version"),
    ("System", "inventory", "Show inventory", "show inventory"),
    ("System", "environment", "Show environment", "show environment"),
    ("System", "cpu", "CPU", "show processes cpu"),
    ("System", "memory", "Memory", "show processes memory"),
    ("System", "logging", "Show logging", "show logging last 50"),
    ("Interfaces", "brief", "Interface summary", "show ip interface brief"),
    ("Interfaces", "status", "Interface status", "show interface status"),
    ("Interfaces", "errors", "Interface errors", "show interface counters errors"),
    ("Layer 2 and 3", "vlan", "VLANs", "show vlan"),
    ("Layer 2 and 3", "mac", "MAC table", "show mac address-table"),
    ("Layer 2 and 3", "stp", "Spanning tree", "show spanning-tree summary"),
    ("Layer 2 and 3", "route", "Routing table", "show ip route"),
    ("Layer 2 and 3", "lldp", "LLDP neighbors", "show lldp neighbors"),
    ("System", "clock", "Clock", "show clock"),
)
# FortiGate `show` prints configuration, including secrets. These are the
# operational read commands instead.
_FORTIGATE = (
    ("System", "status", "System status", "get system status"),
    ("System", "performance", "Performance", "get system performance status"),
    ("Interfaces", "interfaces", "Interfaces", "get system interface physical"),
    ("Layer 2 and 3", "route", "Routing table", "get router info routing-table all"),
    ("Layer 2 and 3", "lldp", "LLDP neighbors", "diagnose lldprx neighbor summary"),
)
_PANOS = (
    ("System", "info", "System info", "show system info"),
    ("Interfaces", "interfaces", "Interfaces", "show interface all"),
    ("Layer 2 and 3", "route", "Routing table", "show routing route"),
    ("Layer 2 and 3", "arp", "ARP", "show arp all"),
    ("Layer 2 and 3", "lldp", "LLDP neighbors", "show lldp neighbors all"),
    ("System", "clock", "Clock", "show clock"),
)

PLATFORMS = {
    "ios": {"label": "Cisco IOS", "prep": ("terminal length 0",), "commands": _IOS},
    "nxos": {"label": "Cisco NX-OS", "prep": ("terminal length 0",), "commands": _NXOS},
    "fortigate": {"label": "FortiGate", "prep": (), "commands": _FORTIGATE},
    "panos": {"label": "PAN-OS", "prep": ("set cli pager off",), "commands": _PANOS},
}


def platform_for(platform_name: str, manufacturer: str) -> str:
    blob = "%s %s" % (platform_name or "", manufacturer or "")
    blob = blob.lower()
    if any(word in blob for word in ("fortigate", "fortios", "fortinet")):
        return "fortigate"
    if any(word in blob for word in ("pan-os", "panos", "palo alto", "paloalto")):
        return "panos"
    if any(word in blob for word in ("nx-os", "nxos", "nexus")):
        return "nxos"
    if any(word in blob for word in ("ios", "catalyst", "cisco")):
        return "ios"
    return ""


def normalize_command(text: str) -> str:
    if not isinstance(text, str):
        raise ApiError(400, "bad_command", "command must be a string")
    if any(ord(char) < 32 for char in text):
        raise ApiError(400, "bad_command", "command must not contain control characters")
    if any(token in text for token in _FORBIDDEN):
        raise ApiError(400, "bad_command", "pipes, redirects and command separators are not allowed")
    collapsed = " ".join(text.strip().split())
    if not collapsed or len(collapsed) > 200:
        raise ApiError(400, "bad_command", "command is empty or too long")
    return collapsed


def resolve_command(platform: str, text: str) -> str:
    """Return the canonical command, or raise when it is not on the allowlist."""
    spec = PLATFORMS.get(platform)
    if spec is None:
        raise ApiError(
            409,
            "unsupported_platform",
            "This device platform has no allowlisted CLI. Supported platforms are Cisco IOS, NX-OS, FortiGate and PAN-OS.",
        )
    wanted = normalize_command(text).lower()
    for _group, _cid, _label, command in spec["commands"]:
        if command.lower() == wanted:
            return command
    raise ApiError(
        400,
        "command_not_allowed",
        "That command is not on the read-only allowlist for this platform. Configuration mode and arbitrary shell commands are not available.",
    )


def catalog(platform: str) -> list[dict]:
    spec = PLATFORMS.get(platform)
    if spec is None:
        return []
    rows = []
    for group, cid, label, command in spec["commands"]:
        rows.append({"id": cid, "group": group, "label": label, "command": command})
    return rows


def safe_device_id(device_id: str) -> str:
    key = unquote(device_id or "").strip()
    if not _SAFE_ID.match(key):
        raise ApiError(400, "bad_device", "device id is not valid")
    return key


def secret_directory(settings) -> str:
    raw = getattr(settings, "device_cli_secret_dir", "") or ""
    if raw:
        return raw
    return os.path.join(settings.config_root, "secrets", "device-cli")


def credential_path(settings, device_id: str) -> str:
    return os.path.join(secret_directory(settings), safe_device_id(device_id) + ".json")


def credentials_configured(settings, device_id: str) -> bool:
    return _load_credentials(settings, device_id) is not None


def _load_credentials(settings, device_id: str):
    path = credential_path(settings, device_id)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise ApiError(500, "credentials_unreadable", "CLI credentials for this device could not be read")
    if not isinstance(data, dict):
        return None
    username = data.get("username")
    password = data.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        return None
    if not username.strip() or not password:
        return None
    return username.strip(), password


def save_credentials(settings, device_id: str, username: str, password: str) -> None:
    if not isinstance(username, str) or not isinstance(password, str):
        raise ApiError(400, "bad_credentials", "username and password must be strings")
    username = username.strip()
    if not username or len(username) > 128 or any(ord(char) < 32 or char.isspace() for char in username):
        raise ApiError(400, "bad_credentials", "username must be 1-128 characters without spaces")
    if not password or len(password) > 200 or any(ord(char) < 32 for char in password):
        raise ApiError(400, "bad_credentials", "password must be 1-200 characters without control characters")
    directory = secret_directory(settings)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    path = credential_path(settings, device_id)
    temporary = path + ".tmp"
    payload = json.dumps({"username": username, "password": password})
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _host_ok(ip: str) -> bool:
    if not ip or ip in ("—", "-"):
        return False
    if any(char in ip for char in " \t\r\n;|&`$<>"):
        return False
    return True


class ParamikoRunner:
    """One allowlisted command over SSH. Prep commands are fixed per platform."""

    def run(self, host: str, username: str, password: str, prep: tuple, command: str, timeout: float) -> str:
        try:
            import paramiko
        except ImportError:
            raise ApiError(503, "cli_client_missing", "The SSH client is not installed in ie-config")
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                host,
                port=22,
                username=username,
                password=password,
                timeout=timeout,
                banner_timeout=timeout,
                auth_timeout=timeout,
                allow_agent=False,
                look_for_keys=False,
            )
            channel = client.invoke_shell(width=200, height=80)
            channel.settimeout(0.4)
            _drain(channel, timeout)
            for item in prep:
                channel.send(item + "\n")
                _drain(channel, timeout)
            channel.send(command + "\n")
            output = _drain(channel, timeout)
        except ApiError:
            raise
        except Exception:
            # paramiko exceptions can echo the username. The password must not be added.
            raise ApiError(502, "ssh_failed", "SSH to this device failed. Check the address, the credentials and that TCP 22 is reachable.")
        finally:
            client.close()
        if "(config" in output:
            raise ApiError(409, "config_mode", "The device entered configuration mode. The session was closed and no further command was sent.")
        return output[:_OUTPUT_LIMIT]


def _drain(channel, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    chunks = []
    size = 0
    quiet = 0
    while time.monotonic() < deadline and size < _OUTPUT_LIMIT:
        try:
            data = channel.recv(4096)
        except Exception:
            quiet += 1
            if chunks and quiet >= 2 and _prompt_seen(chunks):
                break
            continue
        if not data:
            break
        quiet = 0
        text = data.decode("utf-8", "replace").replace("\x00", "")
        chunks.append(text)
        size += len(text)
        if _prompt_seen(chunks):
            break
    return "".join(chunks)[:_OUTPUT_LIMIT]


def _prompt_seen(chunks: list[str]) -> bool:
    text = "".join(chunks).rstrip()
    if not text:
        return False
    line = text.splitlines()[-1].strip()
    if "(config" in line:
        return True
    return line.endswith("#") or line.endswith(">") or line.endswith("$")


def require_cli_role(user) -> None:
    if getattr(user, "role", "") not in CLI_ROLES:
        raise ApiError(403, "forbidden", "Device CLI is limited to Administrators and Engineers")


def mount_device_cli(app, user_of, record, runner=None) -> None:
    ssh = runner or ParamikoRunner()

    def fleet() -> FleetService:
        service = getattr(app.state, "fleet", None)
        if service is None:
            service = FleetService(app.state.settings)
            app.state.fleet = service
        return service

    def actor(request: Request):
        user, _csrf = user_of(request)
        require_cli_role(user)
        return user

    @app.get("/api/v1/devices/{device_id}/cli")
    def cli_catalog(device_id: str, request: Request):
        actor(request)
        access = fleet().device_access(device_id)
        platform = platform_for(access["platform"], access["manufacturer"])
        configured = credentials_configured(app.state.settings, access["id"])
        body = {
            "platform": platform,
            "platformLabel": PLATFORMS[platform]["label"] if platform in PLATFORMS else "",
            "commands": catalog(platform),
            "credentialsConfigured": configured,
            "hostname": access["hostname"],
            "mgmtIp": access["ip"] or "",
        }
        if not platform:
            body["message"] = (
                "This device platform has no allowlisted CLI. Supported platforms are Cisco IOS, NX-OS, FortiGate and PAN-OS."
            )
        elif not configured:
            body["message"] = (
                "CLI credentials are not set for this device. An Administrator or Engineer must save them before a command can run."
            )
        else:
            body["message"] = ""
        return body

    @app.put("/api/v1/devices/{device_id}/cli/credentials")
    async def cli_credentials(device_id: str, request: Request):
        user = actor(request)
        access = fleet().device_access(device_id)
        try:
            body = await request.json()
        except Exception:
            raise ApiError(400, "bad_body", "body must be JSON")
        if not isinstance(body, dict):
            raise ApiError(400, "bad_body", "body must be a JSON object")
        save_credentials(app.state.settings, access["id"], body.get("username", ""), body.get("password", ""))
        record(user, request, "ok", "credentials updated")
        return {"ok": True, "configured": True}

    @app.post("/api/v1/devices/{device_id}/cli")
    async def cli_run(device_id: str, request: Request):
        user = actor(request)
        access = fleet().device_access(device_id)
        try:
            body = await request.json()
        except Exception:
            raise ApiError(400, "bad_body", "body must be JSON")
        if not isinstance(body, dict):
            raise ApiError(400, "bad_body", "body must be a JSON object")
        platform = platform_for(access["platform"], access["manufacturer"])
        try:
            command = resolve_command(platform, body.get("command", ""))
        except ApiError as exc:
            record(user, request, "denied", str(body.get("command") or "")[:200])
            raise exc
        loaded = _load_credentials(app.state.settings, access["id"])
        if loaded is None:
            record(user, request, "credentials-not-configured", command)
            raise ApiError(
                409,
                "credentials_not_configured",
                "CLI credentials are not set for this device. An Administrator or Engineer must save them before a command can run.",
            )
        if not _host_ok(access["ip"]):
            record(user, request, "no-address", command)
            raise ApiError(409, "no_management_ip", "This device has no management IP, so SSH was not attempted.")
        username, password = loaded
        spec = PLATFORMS[platform]
        output = ssh.run(access["ip"], username, password, spec["prep"], command, 12)
        record(user, request, "ok", command)
        return {"command": command, "output": output, "platform": platform}
