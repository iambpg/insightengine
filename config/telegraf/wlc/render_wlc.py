#!/usr/bin/env python3
"""Render Telegraf inputs for wireless controllers.

Catalyst 9800 (IOS-XE) per-AP and per-client data comes from model-driven
telemetry (inputs.cisco_telemetry_mdt, gRPC dial-out). This renderer does not
emit SNMP table walks for a 9800 unless IE_WLC_LEGACY_SNMP=1. snmp-exporter
still collects 9800 chassis health and cLApGlobalAPConnectCount.

AireOS has no MDT. It stays on SNMP: bsnAPTable, bsnAPIfLoadParametersTable
(channel utilization and client count) and bsnMobileStation RSSI/SNR. The
station walk is aggregated in Telegraf before Prometheus sees it.

IE_WLC_MDT_TRANSPORT=gnmi renders inputs.gnmi dial-in for each 9800 instead
of relying on dial-out. Username and password come from the environment and
are not written to git.

IE_WLC_TABLE=all|status|clients|radio|channel|stations
IE_WLC_SHARD_COUNT / IE_WLC_SHARD_INDEX split AireOS controllers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import ssl
import urllib.request

# Columns only. Full-table walks are intentionally not used.
IOSXE = {
    "status": {
        "measurement": "ie_wlc_ap",
        "interval": "5m",
        "offset": "0s",
        "timeout": "180s",
        "fields": [
            ("ap_name", "1.3.6.1.4.1.9.9.513.1.1.1.1.5", True),
            ("admin_status", "1.3.6.1.4.1.9.9.513.1.1.1.1.38", False),
            ("uptime_centiseconds", "1.3.6.1.4.1.9.9.513.1.1.1.1.6", False),
        ],
    },
    "clients": {
        "measurement": "ie_wlc_ap",
        "interval": "5m",
        "offset": "180s",
        "timeout": "180s",
        "fields": [
            ("ap_name", "1.3.6.1.4.1.9.9.513.1.1.1.1.5", True),
            ("clients", "1.3.6.1.4.1.9.9.513.1.1.1.1.72", False),
        ],
    },
    "radio": {
        "measurement": "ie_wlc_radio",
        "interval": "10m",
        "offset": "360s",
        "timeout": "240s",
        "fields": [
            ("radio_type", "1.3.6.1.4.1.9.9.513.1.2.1.1.2", False),
        ],
    },
    "channel": {
        # cLApIfLoadChannelUtilization is notify-only. 9800 still serves the
        # AireOS load table for the readable channel and utilization numbers.
        "measurement": "ie_wlc_radio",
        "interval": "10m",
        "offset": "480s",
        "timeout": "240s",
        "fields": [
            ("channel", "1.3.6.1.4.1.14179.2.2.2.1.4", False),
            ("channel_util", "1.3.6.1.4.1.14179.2.2.13.1.3", False),
        ],
    },
}

AIREOS = {
    "status": {
        "measurement": "ie_wlc_ap",
        "interval": "5m",
        "offset": "0s",
        "timeout": "120s",
        "fields": [
            ("ap_name", "1.3.6.1.4.1.14179.2.2.1.1.3", True),
            ("oper_status", "1.3.6.1.4.1.14179.2.2.1.1.6", False),
        ],
    },
    "clients": {
        "measurement": "ie_wlc_radio",
        "interval": "5m",
        "offset": "120s",
        "timeout": "120s",
        "fields": [
            ("clients", "1.3.6.1.4.1.14179.2.2.13.1.4", False),
        ],
    },
    "radio": {
        "measurement": "ie_wlc_radio",
        "interval": "10m",
        "offset": "240s",
        "timeout": "180s",
        "fields": [
            ("channel", "1.3.6.1.4.1.14179.2.2.2.1.4", False),
        ],
    },
    "channel": {
        # bsnAPIfLoadParametersTable. AireOS has no RRM MDT stream.
        "measurement": "ie_wlc_radio",
        "interval": "10m",
        "offset": "300s",
        "timeout": "180s",
        "fields": [
            ("channel_util", "1.3.6.1.4.1.14179.2.2.13.1.3", False),
        ],
    },
    "stations": {
        # bsnMobileStationTable (AP MAC, radio slot) joined with
        # bsnMobileStationStatsTable (RSSI, SNR). Same client-MAC index.
        # Telegraf drops the client identity before Prometheus. See normalize.star.
        "measurement": "ie_wlc_station",
        "interval": "5m",
        "offset": "150s",
        "timeout": "180s",
        "fields": [
            ("ap_mac", "1.3.6.1.4.1.14179.2.1.4.1.4", True),
            ("radio", "1.3.6.1.4.1.14179.2.1.4.1.5", True),
            ("rssi", "1.3.6.1.4.1.14179.2.1.6.1.1", False),
            ("snr", "1.3.6.1.4.1.14179.2.1.6.1.26", False),
        ],
    },
}

# gNMI dial-in paths. Used only when IE_WLC_MDT_TRANSPORT=gnmi.
GNMI_SUBS = (
    ("ie_wlc_client_raw", "/wireless-client-oper:client-oper-data/traffic-stats", "sample", "60s"),
    ("ie_wlc_client_common", "/wireless-client-oper:client-oper-data/common-oper-data", "sample", "60s"),
    ("ie_wlc_rrm", "/wireless-rrm-oper:rrm-oper-data/rrm-measurement", "sample", "60s"),
    ("ie_wlc_ap_mdt", "/wireless-access-point-oper:access-point-oper-data/capwap-data", "on_change", "60s"),
    ("ie_wlc_radio_mdt", "/wireless-access-point-oper:access-point-oper-data/radio-oper-data", "sample", "60s"),
    ("ie_wlc_ssid", "/wireless-access-point-oper:access-point-oper-data/ssid-counters", "sample", "60s"),
)


def _toml(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def platform_kind(platform: str, role: str) -> str:
    text = "%s %s" % (platform or "", role or "")
    text = text.lower()
    if "ios-xe" in text or "iosxe" in text or "9800" in text:
        return "iosxe"
    return "aireos"


def shard_keep(ip: str, count: int, index: int) -> bool:
    if count <= 1:
        return True
    digest = hashlib.sha256(ip.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % count == index


def load_targets(path: str | None, url: str, token: str, ca: str) -> list[dict]:
    if path:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, list) else []
    if not url or not token:
        return []
    request = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    context = ssl.create_default_context(cafile=ca) if ca and os.path.isfile(ca) else ssl.create_default_context()
    with urllib.request.urlopen(request, context=context, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data if isinstance(data, list) else []


def _truthy(value: str) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def _input(agent: str, kind: str, table: str, spec: dict, tags: dict, auth: dict) -> str:
    lines = [
        "[[inputs.snmp]]",
        "  agents = [%s]" % _toml(agent),
        "  interval = %s" % _toml(spec["interval"]),
        "  collection_offset = %s" % _toml(spec["offset"]),
        "  timeout = %s" % _toml(spec["timeout"]),
        "  retries = 1",
        "  max_repetitions = 10",
        "  version = %d" % auth["version"],
    ]
    if auth["version"] == 3:
        lines.extend([
            "  sec_name = %s" % _toml(auth["user"]),
            "  sec_level = %s" % _toml(auth["level"]),
            "  auth_protocol = %s" % _toml(auth["auth_protocol"]),
            "  auth_password = %s" % _toml(auth["auth_password"]),
            "  priv_protocol = %s" % _toml(auth["priv_protocol"]),
            "  priv_password = %s" % _toml(auth["priv_password"]),
        ])
    else:
        lines.append("  community = %s" % _toml(auth["community"]))
    lines.extend([
        "  [inputs.snmp.tags]",
        "    wlc = %s" % _toml(tags["wlc"]),
        "    site = %s" % _toml(tags["site"]),
        "    platform = %s" % _toml(tags["platform"]),
        "    device_role = %s" % _toml(tags["role"]),
        "    wlc_table = %s" % _toml(table),
    ])
    if tags.get("store_clients"):
        lines.append("    store_clients = %s" % _toml(tags["store_clients"]))
    lines.extend([
        "  [[inputs.snmp.table]]",
        "    name = %s" % _toml(spec["measurement"]),
        "    index_as_tag = true",
    ])
    for name, oid, is_tag in spec["fields"]:
        lines.extend([
            "    [[inputs.snmp.table.field]]",
            "      name = %s" % _toml(name),
            "      oid = %s" % _toml(oid),
            "      is_tag = %s" % ("true" if is_tag else "false"),
        ])
    lines.append("")
    return "\n".join(lines)


def auth_for(name: str, env: dict) -> dict:
    if name == "ntt_snmpv3_auth":
        return {
            "version": 3,
            "user": env.get("SNMP_V3_USERNAME") or env.get("SNMP_V3_USER") or "",
            "level": "authPriv",
            "auth_protocol": "SHA256",
            "auth_password": env.get("SNMP_V3_AUTH_PASSWORD") or "",
            "priv_protocol": "AES256",
            "priv_password": env.get("SNMP_V3_PRIV_PASSWORD") or "",
        }
    return {"version": 2, "community": env.get("SNMP_V2_COMMUNITY") or ""}


def _gnmi(agent: str, tags: dict, env: dict) -> str:
    user = env.get("IE_GNMI_USER") or ""
    password = env.get("IE_GNMI_PASSWORD") or ""
    if not user or not password:
        return "# %s: gNMI dial-in skipped, IE_GNMI_USER or IE_GNMI_PASSWORD is empty\n" % tags["wlc"]
    lines = [
        "[[inputs.gnmi]]",
        "  addresses = [%s]" % _toml(agent),
        "  username = %s" % _toml(user),
        "  password = %s" % _toml(password),
        "  redial = \"30s\"",
        "  [inputs.gnmi.tags]",
        "    wlc = %s" % _toml(tags["wlc"]),
        "    site = %s" % _toml(tags["site"]),
        "    platform = %s" % _toml(tags["platform"]),
        "    device_role = %s" % _toml(tags["role"]),
        "    store_clients = %s" % _toml(tags.get("store_clients") or "0"),
    ]
    for name, path, mode, interval in GNMI_SUBS:
        lines.extend([
            "  [[inputs.gnmi.subscription]]",
            "    name = %s" % _toml(name),
            "    path = %s" % _toml(path),
            "    subscription_mode = %s" % _toml(mode),
            "    sample_interval = %s" % _toml(interval),
        ])
    lines.append("")
    return "\n".join(lines)


def render(targets: list[dict], env: dict) -> str:
    table = (env.get("IE_WLC_TABLE") or "all").strip().lower()
    wanted = ["status", "clients", "radio", "channel", "stations"] if table in ("", "all") else [table]
    transport = (env.get("IE_WLC_MDT_TRANSPORT") or "grpc").strip().lower()
    legacy = _truthy(env.get("IE_WLC_LEGACY_SNMP") or "")
    store = "1" if _truthy(env.get("IE_WLC_STORE_CLIENTS") or "") else "0"
    try:
        count = int(env.get("IE_WLC_SHARD_COUNT") or "1")
        index = int(env.get("IE_WLC_SHARD_INDEX") or "0")
    except ValueError:
        count, index = 1, 0
    chunks = [
        "# Generated from NetBox. Do not commit this file.",
        "# 9800 per-AP data is MDT unless IE_WLC_LEGACY_SNMP=1.",
        "# AireOS stays on SNMP, including bsnMobileStation RSSI/SNR.",
        "",
    ]
    for item in targets:
        if not isinstance(item, dict):
            continue
        addresses = item.get("targets") or []
        labels = item.get("labels") or {}
        if not addresses:
            continue
        ip = str(addresses[0])
        if not shard_keep(ip, count, index):
            continue
        platform = str(labels.get("__meta_netbox_platform") or "")
        role = str(labels.get("__meta_netbox_role") or "")
        kind = platform_kind(platform, role)
        tables = IOSXE if kind == "iosxe" else AIREOS
        auth_name = str(labels.get("__meta_netbox_snmp_auth") or "ie_wlc_v2")
        auth = auth_for(auth_name, env)
        tags = {
            "wlc": str(labels.get("__meta_netbox_name") or ip),
            "site": str(labels.get("__meta_netbox_site_name") or ""),
            "platform": platform or kind,
            "role": role or "wireless-controller",
        }
        if kind == "iosxe" and transport == "gnmi":
            chunks.append(_gnmi("%s:9339" % ip, dict(tags, store_clients=store), env))
            continue
        if kind == "iosxe" and not legacy:
            chunks.append(
                "# %s (%s): MDT supersedes SNMP AP tables. "
                "Chassis health and AP count stay on snmp-exporter.\n"
                % (tags["wlc"], ip)
            )
            continue
        if auth["version"] == 2 and not auth.get("community"):
            continue
        if auth["version"] == 3 and not auth.get("user"):
            continue
        for name in wanted:
            spec = tables.get(name)
            if not spec:
                continue
            row_tags = dict(tags)
            if name == "stations":
                row_tags["store_clients"] = store
            chunks.append(_input("udp://%s:161" % ip, kind, name, spec, row_tags, auth))
    return "\n".join(chunks)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("--targets", default=os.environ.get("IE_WLC_TARGETS_FILE") or "")
    args = parser.parse_args()
    token = ""
    token_file = os.environ.get("IE_NETBOX_TOKEN_FILE") or "/run/secrets/netbox_token"
    if os.path.isfile(token_file):
        with open(token_file, "r", encoding="utf-8") as handle:
            token = handle.read().strip()
    try:
        targets = load_targets(
            args.targets or None,
            os.environ.get("IE_NETBOX_SD_URL") or "",
            token,
            os.environ.get("IE_NETBOX_CA") or "/etc/ie-certs/ca.crt",
        )
    except Exception as exc:
        targets = []
        print("wlc target fetch failed: %s" % exc.__class__.__name__)
    text = render(targets, dict(os.environ))
    with open(args.output, "w", encoding="utf-8") as handle:
        handle.write(text)
    print("wrote %s (%d bytes)" % (args.output, len(text)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
