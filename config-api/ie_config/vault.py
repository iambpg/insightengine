"""Read-only view of the install .env.

The list response never includes a secret value. A separate reveal call returns
one key after the administrator re-enters their password. Values are not logged.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Request

from .apps_launcher import public_base
from .auth import client_ip, token_hash, verify_password
from .errors import ApiError

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_ASSIGN = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
# A secret is a whole segment (PASSWORD, TOKEN, KEY, ...), not a substring.
_SECRET = re.compile(
    r"(?:^|_)(?:PASSWORD|PASSWD|PASS|SECRET|TOKEN|COMMUNITY|HASH|PEPPER|"
    r"CREDENTIAL|BEARER|JWT|ENCRYPTION|KEY)(?:_|$)",
    re.I,
)
_MAX_BYTES = 1024 * 1024
_FAIL_LIMIT = 8
_FAIL_WINDOW = 60.0

# Saved from Settings → Vault. Never returned in the clear, including reveal.
WITHHELD_KEYS = (
    "CISCO_API_CLIENT_ID",
    "CISCO_API_CLIENT_SECRET",
    "FORTIMANAGER_URL",
    "FORTIMANAGER_TOKEN",
)
_WITHHELD = set(WITHHELD_KEYS)

REVEAL_SECONDS = 300


@dataclass(frozen=True)
class Endpoint:
    name: str
    port_key: str
    default: str
    scheme: str


@dataclass(frozen=True)
class Group:
    id: str
    name: str
    note: str
    prefixes: tuple[str, ...]
    endpoints: tuple[Endpoint, ...]


GROUPS: tuple[Group, ...] = (
    Group(
        "netbox", "NetBox", "",
        ("NETBOX_",),
        (Endpoint("NetBox", "PORT_NETBOX", "8092", "https"),),
    ),
    Group(
        "grafana", "Grafana", "",
        ("GRAFANA_",),
        (Endpoint("Grafana", "PORT_GRAFANA", "3000", "https"),),
    ),
    Group(
        "prometheus-alertmanager",
        "Prometheus / Alertmanager",
        "Basic auth in front of Prometheus and Alertmanager is enforced by Caddy.",
        ("ALERTMANAGER_", "PROMETHEUS_", "PROM_", "ADMIN_BASIC_"),
        (
            Endpoint("Prometheus", "PORT_PROMETHEUS", "9090", "https"),
            Endpoint("Alertmanager", "PORT_ALERTMANAGER", "8086", "https"),
        ),
    ),
    Group(
        "activepieces", "Activepieces", "",
        ("AP_",),
        (Endpoint("Activepieces", "PORT_ACTIVEPIECES", "8081", "https"),),
    ),
    Group(
        "netdisco", "Netdisco", "",
        ("NETDISCO_",),
        (Endpoint("Netdisco", "PORT_NETDISCO", "5000", "https"),),
    ),
    Group(
        "oxidized", "Oxidized", "",
        ("OXIDIZED_",),
        (Endpoint("Oxidized", "PORT_OXIDIZED", "8888", "https"),),
    ),
    Group(
        "snmp", "SNMP", "",
        ("SNMP_",),
        (
            Endpoint("SNMP exporter", "PORT_SNMP_EXPORTER", "9116", "http"),
            Endpoint("SNMP traps", "PORT_TRAPS", "162", "udp"),
        ),
    ),
    Group(
        "ui-admin", "UI / admin", "",
        ("CLIENT_", "INSTALL_", "PUBLIC_", "HOST_", "SETUP_", "IE_", "DOCKER_",
         "COMPOSE_", "MONITORING_", "HTTPS_", "ALERT_WEBHOOK_"),
        (
            Endpoint("InsightEngine HTTPS", "PORT_HTTPS", "443", "https"),
            Endpoint("InsightEngine HTTP", "PORT_HTTP", "18086", "http"),
            Endpoint("HTTP/3", "PORT_HTTP3", "443", "udp"),
        ),
    ),
    Group(
        "other", "Other", "",
        (),
        (
            Endpoint("blackbox exporter", "PORT_BLACKBOX", "9115", "http"),
            Endpoint("syslog", "PORT_SYSLOG", "514", "tcp"),
        ),
    ),
)

_BY_ID = {group.id: group for group in GROUPS}

PORT_GROUP = {
    endpoint.port_key: group.id
    for group in GROUPS
    for endpoint in group.endpoints
}
PORT_GROUP["HTTPS_PORT_SUFFIX"] = "ui-admin"


def is_secret_key(key: str) -> bool:
    return bool(_SECRET.search(key))


def parse_env(text: str) -> list[tuple[str, str]]:
    """Last assignment wins. Comments and blank lines are dropped. Values are unquoted."""
    found: dict[str, str] = {}
    order: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        matched = _ASSIGN.match(line)
        if not matched:
            continue
        key, raw_value = matched.group(1), matched.group(2)
        if not _KEY_RE.match(key):
            continue
        if key not in found:
            order.append(key)
        found[key] = _unquote(raw_value)
    return [(key, found[key]) for key in order]


def _unquote(raw: str) -> str:
    value = raw.strip()
    if value.startswith("'"):
        end = value.find("'", 1)
        return value[1:] if end < 0 else value[1:end]
    if value.startswith('"'):
        end = value.find('"', 1)
        return value[1:] if end < 0 else value[1:end]
    comment = value.find(" #")
    if comment >= 0:
        value = value[:comment].rstrip()
    return value


def env_path(settings) -> str:
    explicit = getattr(settings, "env_file", "") or ""
    if explicit:
        return explicit
    root = getattr(settings, "config_root", "") or ""
    return os.path.join(root, ".env")


def read_env(settings) -> list[tuple[str, str]]:
    path = env_path(settings)
    try:
        if not os.path.isfile(path) or os.path.isdir(path):
            raise ApiError(503, "env_unavailable", "The install .env is not mounted into ie-config")
        size = os.path.getsize(path)
    except OSError:
        raise ApiError(503, "env_unavailable", "The install .env is not mounted into ie-config")
    if size > _MAX_BYTES:
        raise ApiError(413, "too_large", "the env file is larger than 1 MB")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read(_MAX_BYTES + 1)
    except OSError:
        raise ApiError(503, "env_unavailable", "The install .env is not mounted into ie-config")
    if len(text.encode("utf-8", "replace")) > _MAX_BYTES:
        raise ApiError(413, "too_large", "the env file is larger than 1 MB")
    return parse_env(text)


def group_id_for(key: str) -> str:
    mapped = PORT_GROUP.get(key)
    if mapped:
        return mapped
    best_len = 0
    best = "other"
    for group in GROUPS:
        for prefix in group.prefixes:
            if key.startswith(prefix) and len(prefix) > best_len:
                best_len = len(prefix)
                best = group.id
    return best


def _port_value(values: dict[str, str], endpoint: Endpoint) -> str:
    raw = (values.get(endpoint.port_key) or "").strip()
    if raw.isdigit() and 1 <= int(raw) <= 65535:
        return raw
    return endpoint.default


def _endpoint_view(endpoint: Endpoint, values: dict[str, str], host: str) -> dict:
    port = _port_value(values, endpoint)
    url = ""
    if endpoint.scheme in ("http", "https"):
        url = public_base(host, port, endpoint.scheme)
    return {
        "name": endpoint.name,
        "portKey": endpoint.port_key,
        "port": int(port),
        "scheme": endpoint.scheme,
        "url": url,
    }


def list_view(pairs: list[tuple[str, str]], host: str) -> dict:
    """Grouped keys. Secret values are omitted."""
    values = dict(pairs)
    buckets: dict[str, list[dict]] = {group.id: [] for group in GROUPS}
    for key, value in pairs:
        if key in _WITHHELD:
            continue
        secret = is_secret_key(key)
        item = {"key": key, "secret": secret, "set": value != ""}
        if not secret:
            item["value"] = value
        buckets[group_id_for(key)].append(item)
    groups = []
    for group in GROUPS:
        groups.append({
            "id": group.id,
            "name": group.name,
            "note": group.note,
            "endpoints": [_endpoint_view(item, values, host) for item in group.endpoints],
            "entries": buckets[group.id],
        })
    return {"readOnly": True, "revealSeconds": REVEAL_SECONDS, "groups": groups}


def integrations_path(settings) -> str:
    root = getattr(settings, "config_root", "") or ""
    return os.path.join(root, "data", "vault", "integrations.env")


def _stored_pairs(path: str) -> list[tuple[str, str]]:
    try:
        if not os.path.isfile(path):
            return []
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read(_MAX_BYTES)
    except OSError:
        return []
    return parse_env(text)


def secret_value(settings, key: str) -> str:
    """Integration secret. Integrations file, then .env, then the process environment.

    The value is for the caller to use. Do not log it.
    """
    if key not in _WITHHELD:
        return ""
    for _name, value in _stored_pairs(integrations_path(settings)):
        if _name == key and value.strip():
            return value.strip()
    try:
        pairs = read_env(settings)
    except ApiError:
        pairs = []
    for name, value in pairs:
        if name == key and value.strip():
            return value.strip()
    env = (os.environ.get(key) or "").strip()
    if env and env != "unset-placeholder":
        return env
    return ""


def integration_status(settings) -> dict:
    return {
        "cisco": {
            "idSet": bool(secret_value(settings, "CISCO_API_CLIENT_ID")),
            "secretSet": bool(secret_value(settings, "CISCO_API_CLIENT_SECRET")),
        },
        "fortimanager": {
            "urlSet": bool(secret_value(settings, "FORTIMANAGER_URL")),
            "tokenSet": bool(secret_value(settings, "FORTIMANAGER_TOKEN")),
        },
    }


def _quote_env(value: str) -> str:
    if any(ch in value for ch in ("'", "\n", "\r", "\x00")):
        raise ApiError(400, "bad_value", "that value cannot be stored safely")
    return "'" + value + "'"


def save_integrations(settings, updates: dict[str, str]) -> dict:
    """Write only the allow-listed keys. A blank value keeps the stored one."""
    if not isinstance(updates, dict):
        raise ApiError(400, "bad_body", "body must be a JSON object")
    current = dict(_stored_pairs(integrations_path(settings)))
    for key in WITHHELD_KEYS:
        if key not in updates:
            continue
        value = updates[key]
        if value is None:
            continue
        if not isinstance(value, str):
            raise ApiError(400, "bad_value", "values must be strings")
        if value == "":
            continue
        if len(value) > 512:
            raise ApiError(400, "bad_value", "value is too long")
        if key == "FORTIMANAGER_URL":
            lowered = value.strip().lower()
            if not (lowered.startswith("https://") or lowered.startswith("http://")):
                raise ApiError(400, "bad_value", "FortiManager URL must start with http:// or https://")
        current[key] = value.strip()
    path = integrations_path(settings)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = ["# NetBridge integration credentials. Values are not logged.", ""]
    for key in WITHHELD_KEYS:
        if current.get(key):
            lines.append("%s=%s" % (key, _quote_env(current[key])))
    body = "\n".join(lines) + "\n"
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, body.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    os.chmod(path, 0o600)
    return integration_status(settings)


def lookup_value(pairs: list[tuple[str, str]], key: str) -> str:
    if key in _WITHHELD:
        raise ApiError(403, "secret_withheld", "this value is never shown")
    if not _KEY_RE.match(key):
        raise ApiError(400, "bad_key", "key is not valid")
    for name, value in pairs:
        if name == key:
            return value
    raise ApiError(404, "not_found", "unknown key")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def grant(sessions: dict, token: str, seconds: int, now: datetime | None = None) -> None:
    current = now or now_utc()
    sessions[token] = current + timedelta(seconds=seconds)


def session_open(sessions: dict, token: str, now: datetime | None = None) -> bool:
    exp = sessions.get(token)
    if exp is None:
        return False
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    current = now or now_utc()
    if exp <= current:
        sessions.pop(token, None)
        return False
    return True


def too_many_failures(bucket: dict, key: str, now: float) -> bool:
    recent = [stamp for stamp in bucket.get(key, []) if now - stamp < _FAIL_WINDOW]
    bucket[key] = recent
    return len(recent) >= _FAIL_LIMIT


def note_failure(bucket: dict, key: str, now: float) -> None:
    bucket.setdefault(key, []).append(now)


def reveal_seconds(settings) -> int:
    raw = getattr(settings, "vault_reveal_seconds", REVEAL_SECONDS)
    try:
        seconds = int(raw)
    except (TypeError, ValueError):
        return REVEAL_SECONDS
    if seconds < 60 or seconds > 900:
        return REVEAL_SECONDS
    return seconds


def _json_object(body) -> dict:
    if not isinstance(body, dict):
        raise ApiError(400, "bad_body", "body must be a JSON object")
    return body


def mount_vault(app, user_of, audit) -> None:
    app.state.vault_sessions = {}
    app.state.vault_failures = {}

    def require_admin(user) -> None:
        from .auth import is_admin
        if not is_admin(getattr(user, "role", "")):
            raise ApiError(403, "forbidden", "Vault is limited to Administrators")

    def session_token(request: Request) -> str:
        raw = request.cookies.get(app.state.settings.cookie_name) or ""
        return token_hash(raw) if raw else ""

    @app.get("/api/v1/settings/vault")
    def vault_list(request: Request):
        user, _csrf = user_of(request)
        require_admin(user)
        settings = app.state.settings
        pairs = read_env(settings)
        seconds = reveal_seconds(settings)
        payload = list_view(pairs, getattr(settings, "public_host", "") or "")
        payload["revealSeconds"] = seconds
        payload["integrations"] = integration_status(settings)
        return payload

    @app.post("/api/v1/settings/vault/unlock")
    async def vault_unlock(request: Request):
        user, _csrf = user_of(request)
        require_admin(user)
        try:
            body = _json_object(await request.json())
        except ApiError:
            raise
        except Exception:
            raise ApiError(400, "bad_body", "body must be JSON")
        password = body.get("password")
        ip = _client_ip(request)
        fail_key = str(getattr(user, "id", "") or "")
        now = datetime.now(timezone.utc).timestamp()
        if too_many_failures(app.state.vault_failures, fail_key, now):
            raise ApiError(429, "rate_limited", "too many password attempts; wait a minute")
        # The password is checked and then dropped. It is not logged or audited.
        if not isinstance(password, str) or not password or not verify_password(password, user.password_hash):
            note_failure(app.state.vault_failures, fail_key, now)
            audit(app.state.sf, user, "vault-unlock", ip, "denied", "vault", "", "", "")
            raise ApiError(401, "invalid_credentials", "password is not correct")
        app.state.vault_failures.pop(fail_key, None)
        seconds = reveal_seconds(app.state.settings)
        grant(app.state.vault_sessions, session_token(request), seconds)
        audit(app.state.sf, user, "vault-unlock", ip, "ok", "vault", "", "", "")
        return {"ok": True, "expiresIn": seconds}

    @app.post("/api/v1/settings/vault/reveal")
    async def vault_reveal(request: Request):
        user, _csrf = user_of(request)
        require_admin(user)
        try:
            body = _json_object(await request.json())
        except ApiError:
            raise
        except Exception:
            raise ApiError(400, "bad_body", "body must be JSON")
        key = body.get("key")
        action = body.get("action") or "reveal"
        if action not in ("reveal", "copy"):
            raise ApiError(400, "bad_action", "action must be reveal or copy")
        if not isinstance(key, str):
            raise ApiError(400, "bad_key", "key is not valid")
        pairs = read_env(app.state.settings)
        value = lookup_value(pairs, key)
        if is_secret_key(key) and not session_open(app.state.vault_sessions, session_token(request)):
            raise ApiError(
                403, "reauth_required",
                "enter the current administrator password to reveal a value",
            )
        audit(
            app.state.sf, user, "vault-" + action, _client_ip(request), "ok",
            "vault", key, "", "",
        )
        return {"key": key, "value": value, "action": action}

    @app.post("/api/v1/settings/vault/integrations")
    async def vault_save_integrations(request: Request):
        user, _csrf = user_of(request)
        require_admin(user)
        try:
            body = _json_object(await request.json())
        except ApiError:
            raise
        except Exception:
            raise ApiError(400, "bad_body", "body must be JSON")
        mapping = {
            "CISCO_API_CLIENT_ID": body.get("ciscoClientId", body.get("CISCO_API_CLIENT_ID")),
            "CISCO_API_CLIENT_SECRET": body.get("ciscoClientSecret", body.get("CISCO_API_CLIENT_SECRET")),
            "FORTIMANAGER_URL": body.get("fortimanagerUrl", body.get("FORTIMANAGER_URL")),
            "FORTIMANAGER_TOKEN": body.get("fortimanagerToken", body.get("FORTIMANAGER_TOKEN")),
        }
        # Drop keys the client omitted so a partial form does not clear them.
        updates = {key: value for key, value in mapping.items() if value is not None}
        saved = save_integrations(app.state.settings, updates)
        audit(app.state.sf, user, "vault-integrations", _client_ip(request), "ok", "vault", "", "", "")
        return {"ok": True, "integrations": saved}

    @app.post("/api/v1/settings/vault/integrations/test")
    async def vault_test_integrations(request: Request):
        user, _csrf = user_of(request)
        require_admin(user)
        try:
            body = _json_object(await request.json())
        except ApiError:
            raise
        except Exception:
            raise ApiError(400, "bad_body", "body must be JSON")
        target = body.get("target")
        if target == "cisco":
            client = getattr(app.state, "eox_client", None)
            if client is None:
                from .netbridge.eox import EoxClient
                client = EoxClient(
                    secret_value(app.state.settings, "CISCO_API_CLIENT_ID"),
                    secret_value(app.state.settings, "CISCO_API_CLIENT_SECRET"),
                    pause=0,
                )
            result = client.probe()
        elif target == "fortimanager":
            from .netbridge.sources import fmg_list
            listed = fmg_list(
                secret_value(app.state.settings, "FORTIMANAGER_URL"),
                secret_value(app.state.settings, "FORTIMANAGER_TOKEN"),
                http=getattr(app.state, "fmg_http", None),
            )
            count = len(listed.get("devices") or [])
            if listed.get("ok"):
                result = {"ok": True, "message": "Connected. %d managed devices." % count}
            else:
                result = {"ok": False, "message": listed.get("message") or "FortiManager did not answer"}
        else:
            raise ApiError(400, "bad_body", "target must be cisco or fortimanager")
        audit(
            app.state.sf, user, "vault-integration-test", _client_ip(request),
            "ok" if result.get("ok") else "failed", "vault", "", "", str(target),
        )
        return result


def _client_ip(request) -> str:
    return client_ip(request)
