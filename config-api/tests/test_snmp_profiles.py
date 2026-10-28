"""SNMP config-context resolution. No live NetBox."""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "config-api"))

from ie_config.snmp_profiles import (  # noqa: E402
    SnmpProfileError,
    auth_name,
    fallback_from_env,
    public_view,
    resolve_device,
    response_contains_secret,
    splice_auths,
    validate_profile,
)
from ie_config.snmp_sync import (  # noqa: E402
    auth_map_from_rows,
    grouped_profiles,
    iter_resolved,
    snmp_v2c_get,
    snmp_v2c_get_packet,
    splice_device_auth,
    write_outputs,
)
def _load_sd():
    path = ROOT / "netbox" / "netbox_lists" / "sd.py"
    spec = importlib.util.spec_from_file_location("netbox_lists_sd", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


target_for = _load_sd().target_for

EXAMPLE = {
    "version": "3",
    "port": 161,
    "security_name": "mon-user",
    "security_level": "authPriv",
    "auth_protocol": "SHA",
    "auth_passphrase": "auth-secret-value",
    "priv_protocol": "AES",
    "priv_passphrase": "priv-secret-value",
}
COMMUNITY = "community-secret-value"


def test_example_profile_and_public_view_hide_secrets():
    profile = validate_profile(EXAMPLE)
    view = public_view(profile, auth=auth_name(profile), source="context", weight=50, name="branch")
    leaked = response_contains_secret(view, ["auth-secret-value", "priv-secret-value"])
    assert leaked == ""
    assert view["has_auth_passphrase"] is True
    assert view["has_priv_passphrase"] is True
    assert view["security_name"] == "mon-user"
    assert view["auth"].startswith("ie_snmp_")
    assert "devices" not in view


def test_per_device_field_is_rejected():
    try:
        validate_profile(dict(EXAMPLE, devices=[1]))
    except SnmpProfileError as exc:
        assert "per-device" in str(exc)
    else:
        raise AssertionError("per-device field was accepted")


def test_context_wins_and_env_is_the_fallback():
    env = {
        "SNMP_V3_USERNAME": "env-user",
        "SNMP_V3_AUTH_PASSWORD": "env-auth",
        "SNMP_V3_PRIV_PASSWORD": "env-priv",
        "SNMP_V2_COMMUNITY": COMMUNITY,
    }
    context = resolve_device({"monitoring_snmp": EXAMPLE}, env, {})
    assert context["source"] == "context"
    assert context["auth"] != "ntt_snmpv3_auth"
    fallback = resolve_device({}, env, {})
    assert fallback["source"] == "env"
    assert fallback["auth"] == "ntt_snmpv3_auth"
    assert fallback_from_env({"SNMP_V2_COMMUNITY": "unset-placeholder"}) is None
    named = resolve_device(
        {"monitoring_snmp": {"profile": "branch-a"}},
        env,
        {"branch-a": {"version": "2c", "community": COMMUNITY}},
    )
    assert named["source"] == "file"
    assert named["profile"]["community"] == COMMUNITY
    rows = iter_resolved(
        [
            {"id": 1, "name": "sw1", "primary_ip4": "10.1.1.1/24", "role": "access-switch", "config_context": {"monitoring_snmp": EXAMPLE}},
            {"id": 2, "name": "sw2", "primary_ip4": "10.1.1.2/24", "role": "access-switch", "config_context": {}},
        ],
        env,
        {},
    )
    mapping = auth_map_from_rows(rows)
    assert mapping["10.1.1.1"] == context["auth"]
    assert "10.1.1.2" not in mapping
    assert len(grouped_profiles(rows)) == 1


def test_different_secrets_get_different_auth_names():
    one = validate_profile(EXAMPLE)
    two = validate_profile(dict(EXAMPLE, auth_passphrase="other-auth-secret"))
    assert auth_name(one) != auth_name(two)


def test_runtime_file_adds_auths_and_hides_them_from_the_map(tmp_path):
    base = "auths:\n  ntt_snmpv3_auth:\n    version: 3\nmodules:\n  if_mib: {}\n"
    base_path = tmp_path / "snmp.yml"
    base_path.write_text(base, encoding="utf-8")
    profile = validate_profile(dict(EXAMPLE, community=None) if False else EXAMPLE)
    rows = iter_resolved(
        [{"id": 7, "name": "sw", "primary_ip4": "10.9.9.9", "config_context": {"monitoring_snmp": profile}}],
        {},
        {},
    )
    summary = write_outputs(str(tmp_path), str(base_path), rows)
    assert summary["profiles"] == 1
    runtime = (tmp_path / "snmp.runtime.yml").read_text(encoding="utf-8")
    assert "modules:" in runtime
    assert "if_mib" in runtime
    assert auth_name(profile) in runtime
    assert "auth-secret-value" in runtime
    auth_map = (tmp_path / "auth-by-ip.yml").read_text(encoding="utf-8")
    assert "auth-secret-value" not in auth_map
    assert "10.9.9.9" in auth_map
    assert (tmp_path / "snmp.runtime.yml").stat().st_mode & 0o777 == 0o600
    spliced = splice_auths(base, {})
    assert spliced == base


def test_http_sd_uses_resolved_auth_and_keeps_the_default_without_one():
    device = {
        "name": "sw1", "primary_ip4": "10.2.2.2", "role": "access-switch",
        "site": "A", "device_type": "C9300", "region": "", "tenant": "",
        "site_group": "", "platform": "ios", "manufacturer": "cisco",
        "snmp_module": "", "snmp_auth": "",
    }
    plain = target_for(device, {})
    assert plain["labels"]["__meta_netbox_snmp_auth"] == "ntt_snmpv3_auth"
    resolved = target_for(device, {}, {"10.2.2.2": "ie_snmp_abc123abc123"})
    assert resolved["labels"]["__meta_netbox_snmp_auth"] == "ie_snmp_abc123abc123"


def test_netdisco_specific_entries_precede_the_default():
    rendered = "device_auth:\n  - tag: default\n    community: ${SNMP_V2_COMMUNITY}\n"
    extra = "- tag: ie_snmp_abc\n  only:\n  - 10.1.1.1\n  community: hidden\n"
    merged = splice_device_auth(rendered, extra)
    assert merged.index("ie_snmp_abc") < merged.index("tag: default")


def test_v2c_packet_contains_the_community_and_the_result_does_not():
    packet = snmp_v2c_get_packet(COMMUNITY)
    assert COMMUNITY.encode() in packet
    assert b"\x2b\x06\x01\x02\x01\x01\x01\x00" in packet

    def send(payload, host, port, timeout):
        assert COMMUNITY.encode() in payload
        return b"\x30\x03\x02\x01\x01"

    result = snmp_v2c_get("10.1.1.1", COMMUNITY, send=send)
    assert result["ok"] is True
    assert response_contains_secret(result, [COMMUNITY]) == ""
    blob = json.dumps(result)
    assert COMMUNITY not in blob
