"""Resolve NetBox ``monitoring_snmp`` config contexts into exporter auth names.

NetBox already merges contexts by scope and weight. This module only reads the
rendered ``config_context`` and never invents a per-device field. Secret values
are not included in public views or log lines.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

SECRET_KEYS = ("community", "auth_passphrase", "priv_passphrase")
VERSIONS = ("2c", "3")
LEVELS = ("noAuthNoPriv", "authNoPriv", "authPriv")
AUTH_PROTOCOLS = ("MD5", "SHA", "SHA224", "SHA256", "SHA384", "SHA512")
PRIV_PROTOCOLS = ("DES", "AES", "AES192", "AES256", "AES256C")
SCOPE_KEYS = ("site_groups", "sites", "regions", "roles", "platforms", "tenants")

# Existing snmp.yml names. Used only when a device has no monitoring_snmp context.
ENV_V3_AUTH = "ntt_snmpv3_auth"
ENV_V2_AUTH = "ie_snmp_v2"


class SnmpProfileError(ValueError):
    pass


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def canonical(profile: dict) -> str:
    """Stable JSON for hashing. Includes secrets so two communities do not collide."""
    keys = (
        "version", "port", "community", "security_name", "security_level",
        "auth_protocol", "auth_passphrase", "priv_protocol", "priv_passphrase", "context_name",
    )
    body = {key: profile.get(key) for key in keys if profile.get(key) not in (None, "")}
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


def auth_name(profile: dict) -> str:
    digest = hashlib.sha256(canonical(profile).encode("utf-8")).hexdigest()[:12]
    return "ie_snmp_" + digest


def validate_profile(raw: Any) -> dict:
    """Return a normalised profile or raise SnmpProfileError. Does not log the value."""
    if not isinstance(raw, dict):
        raise SnmpProfileError("monitoring_snmp must be an object")
    if "devices" in raw:
        raise SnmpProfileError("monitoring_snmp has no per-device field; scope the config context instead")
    version = _text(raw.get("version"))
    if version not in VERSIONS:
        raise SnmpProfileError("version must be 2c or 3")
    port = raw.get("port", 161)
    try:
        port_i = int(port)
    except (TypeError, ValueError):
        raise SnmpProfileError("port must be an integer")
    if port_i < 1 or port_i > 65535:
        raise SnmpProfileError("port must be 1-65535")
    profile: dict[str, Any] = {"version": version, "port": port_i}
    context_name = _text(raw.get("context_name"))
    if context_name:
        profile["context_name"] = context_name
    if version == "2c":
        community = _text(raw.get("community"))
        if not community:
            raise SnmpProfileError("version 2c requires community")
        profile["community"] = community
        return profile
    security_name = _text(raw.get("security_name"))
    level = _text(raw.get("security_level")) or "noAuthNoPriv"
    if not security_name:
        raise SnmpProfileError("version 3 requires security_name")
    if level not in LEVELS:
        raise SnmpProfileError("security_level is not recognised")
    profile["security_name"] = security_name
    profile["security_level"] = level
    if level in ("authNoPriv", "authPriv"):
        proto = _text(raw.get("auth_protocol")) or "SHA"
        if proto not in AUTH_PROTOCOLS:
            raise SnmpProfileError("auth_protocol is not recognised")
        passphrase = _text(raw.get("auth_passphrase"))
        if not passphrase:
            raise SnmpProfileError("auth_passphrase is required for this security_level")
        profile["auth_protocol"] = proto
        profile["auth_passphrase"] = passphrase
    if level == "authPriv":
        proto = _text(raw.get("priv_protocol")) or "AES"
        if proto not in PRIV_PROTOCOLS:
            raise SnmpProfileError("priv_protocol is not recognised")
        passphrase = _text(raw.get("priv_passphrase"))
        if not passphrase:
            raise SnmpProfileError("priv_passphrase is required for authPriv")
        profile["priv_protocol"] = proto
        profile["priv_passphrase"] = passphrase
    return profile


def public_view(profile: dict, *, auth: str, source: str, scopes: dict | None = None, weight: int | None = None, name: str = "", ips: list[str] | None = None) -> dict:
    """API shape. Secret fields are presence flags only."""
    view = {
        "name": name,
        "auth": auth,
        "source": source,
        "version": profile.get("version"),
        "port": profile.get("port", 161),
        "security_name": profile.get("security_name") or "",
        "security_level": profile.get("security_level") or "",
        "auth_protocol": profile.get("auth_protocol") or "",
        "priv_protocol": profile.get("priv_protocol") or "",
        "context_name": profile.get("context_name") or "",
        "has_community": bool(profile.get("community")),
        "has_auth_passphrase": bool(profile.get("auth_passphrase")),
        "has_priv_passphrase": bool(profile.get("priv_passphrase")),
        "scopes": {key: list((scopes or {}).get(key) or []) for key in SCOPE_KEYS},
        "weight": weight,
        "applies_to": list(ips or []),
    }
    return view


def fallback_from_env(env: dict[str, str] | None) -> dict | None:
    """The .env SNMP_* values, used only when a device has no monitoring_snmp context."""
    env = env or {}
    user = _text(env.get("SNMP_V3_USERNAME") or env.get("SNMP_V3_USER"))
    auth_pass = _text(env.get("SNMP_V3_AUTH_PASSWORD"))
    priv_pass = _text(env.get("SNMP_V3_PRIV_PASSWORD"))
    community = _text(env.get("SNMP_V2_COMMUNITY"))
    if user and user != "unset-placeholder" and auth_pass and auth_pass != "unset-placeholder":
        raw = {
            "version": "3",
            "port": 161,
            "security_name": user,
            "security_level": "authPriv" if priv_pass and priv_pass != "unset-placeholder" else "authNoPriv",
            "auth_protocol": "SHA",
            "auth_passphrase": auth_pass,
        }
        if priv_pass and priv_pass != "unset-placeholder":
            raw["priv_protocol"] = "AES"
            raw["priv_passphrase"] = priv_pass
        try:
            return validate_profile(raw)
        except SnmpProfileError:
            return None
    if community and community != "unset-placeholder":
        try:
            return validate_profile({"version": "2c", "port": 161, "community": community})
        except SnmpProfileError:
            return None
    return None


def env_auth_name(profile: dict) -> str:
    return ENV_V2_AUTH if profile.get("version") == "2c" else ENV_V3_AUTH


def monitoring_snmp_from_context(config_context: Any) -> Any:
    if not isinstance(config_context, dict):
        return None
    if "monitoring_snmp" in config_context:
        return config_context.get("monitoring_snmp")
    return None


def _invalid_fallback(env, name: str, exc: Exception) -> dict:
    """A broken monitoring_snmp must not stop the sync: the device keeps the .env scrape path.

    ``invalid`` carries the validation message (it never contains a secret value).
    """
    fallback = fallback_from_env(env)
    out = {"profile": fallback, "auth": env_auth_name(fallback) if fallback else "", "source": "env",
           "profile_name": name, "invalid": str(exc)}
    return out


def resolve_device(config_context: Any, env: dict[str, str] | None, file_profiles: dict | None) -> dict:
    """Resolve one rendered config context.

    Returns ``{"profile", "auth", "source"}``. ``source`` is ``context``,
    ``file``, or ``env``. An empty profile means nothing to monitor with SNMP.
    """
    raw = monitoring_snmp_from_context(config_context)
    file_profiles = file_profiles or {}
    if isinstance(raw, dict) and raw.get("profile") and "version" not in raw:
        name = _text(raw.get("profile"))
        stored = file_profiles.get(name)
        if isinstance(stored, dict):
            try:
                profile = validate_profile(stored)
            except SnmpProfileError as exc:
                return _invalid_fallback(env, name, exc)
            return {"profile": profile, "auth": auth_name(profile), "source": "file", "profile_name": name}
        # Named profile missing from the root file: do not invent secrets.
        fallback = fallback_from_env(env)
        if fallback is None:
            return {"profile": None, "auth": "", "source": "env", "profile_name": name}
        return {"profile": fallback, "auth": env_auth_name(fallback), "source": "env", "profile_name": name}
    if isinstance(raw, dict) and raw.get("version"):
        try:
            profile = validate_profile(raw)
        except SnmpProfileError as exc:
            return _invalid_fallback(env, "", exc)
        return {"profile": profile, "auth": auth_name(profile), "source": "context", "profile_name": ""}
    fallback = fallback_from_env(env)
    if fallback is None:
        return {"profile": None, "auth": "", "source": "env", "profile_name": ""}
    return {"profile": fallback, "auth": env_auth_name(fallback), "source": "env", "profile_name": ""}


def exporter_auth(profile: dict) -> dict:
    """One snmp_exporter ``auths:`` entry. Caller writes it to a root-only file."""
    if profile.get("version") == "2c":
        return {
            "community": profile["community"],
            "security_level": "noAuthNoPriv",
            "version": 2,
        }
    body: dict[str, Any] = {
        "version": 3,
        "security_level": profile.get("security_level") or "noAuthNoPriv",
        "username": profile.get("security_name") or "",
    }
    if profile.get("auth_protocol"):
        body["auth_protocol"] = profile["auth_protocol"]
        body["password"] = profile.get("auth_passphrase") or ""
    if profile.get("priv_protocol"):
        body["priv_protocol"] = profile["priv_protocol"]
        body["priv_password"] = profile.get("priv_passphrase") or ""
    if profile.get("context_name"):
        body["context_name"] = profile["context_name"]
    return body


def escape_exporter(value: str) -> str:
    """snmp_exporter expands ``$`` when ``--config.expand-environment-variables`` is set."""
    return value.replace("$", "$$")


def netdisco_entry(profile: dict, ips: list[str], tag: str) -> dict:
    """One Netdisco ``device_auth`` item. ``only`` limits it to these addresses."""
    item: dict[str, Any] = {"tag": tag, "only": list(ips)}
    if profile.get("version") == "2c":
        item["community"] = profile.get("community") or ""
        return item
    item["user"] = profile.get("security_name") or ""
    if profile.get("auth_protocol"):
        item["auth"] = {"proto": profile["auth_protocol"], "pass": profile.get("auth_passphrase") or ""}
    if profile.get("priv_protocol"):
        item["priv"] = {"proto": profile["priv_protocol"], "pass": profile.get("priv_passphrase") or ""}
    return item


def splice_auths(snmp_yml: str, extra: dict[str, dict]) -> str:
    """Insert auth blocks before ``modules:`` without rewriting the module catalog."""
    if not extra:
        return snmp_yml
    import yaml
    rendered = yaml.safe_dump(extra, sort_keys=False, default_flow_style=False).strip("\n")
    indented = "\n".join("  " + line if line else line for line in rendered.splitlines())
    addition = indented + "\n"
    marker = "\nmodules:"
    idx = snmp_yml.find(marker)
    if idx == -1:
        if not snmp_yml.endswith("\n"):
            snmp_yml += "\n"
        return snmp_yml + addition
    return snmp_yml[:idx] + "\n" + addition + snmp_yml[idx:]


def build_context_data(profile: dict, secret_mode: str, profile_name: str) -> dict:
    """What NetBox stores. File mode keeps only the profile name in the context."""
    if secret_mode == "file":
        if not profile_name:
            raise SnmpProfileError("file mode requires a profile name")
        return {"monitoring_snmp": {"profile": profile_name}}
    if "devices" in profile:
        raise SnmpProfileError("refusing a per-device SNMP field")
    return {"monitoring_snmp": dict(profile)}


def response_contains_secret(payload: Any, secrets: list[str]) -> str:
    """Return the first secret that leaked into a JSON-able payload, else ''."""
    blob = json.dumps(payload, default=str)
    for secret in secrets:
        if secret and secret in blob:
            return secret
    return ""
