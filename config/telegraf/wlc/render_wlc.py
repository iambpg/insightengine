#!/usr/bin/env python3
"""Render Telegraf SNMP inputs for wireless controllers.

One input per WLC per table. A Catalyst 9800 with ~5000 APs is split into
status, client counts, radio identity and channel utilization, with staggered
collection_offset values so the controller is not walked four ways at once.

NetBox HTTP SD (the same prometheus-devices list Prometheus uses) supplies
targets. SNMP communities and v3 passwords come from the environment, the
same variables snmp-exporter already uses. Nothing secret is written to git.

IE_WLC_TABLE=all|status|clients|radio|channel
IE_WLC_SHARD_COUNT / IE_WLC_SHARD_INDEX split controllers across processes.
The 5000-AP 9800 should be the only controller on its Telegraf (shard it
alone, or run IE_WLC_TABLE as four processes).
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
        "measurement": "ie_wlc_radio",
        "interval": "10m",
        "offset": "300s",
        "timeout": "180s",
        "fields": [
            ("channel_util", "1.3.6.1.4.1.14179.2.2.13.1.3", False),
        ],
    },
}


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


def render(targets: list[dict], env: dict) -> str:
    table = (env.get("IE_WLC_TABLE") or "all").strip().lower()
    wanted = ["status", "clients", "radio", "channel"] if table in ("", "all") else [table]
    try:
        count = int(env.get("IE_WLC_SHARD_COUNT") or "1")
        index = int(env.get("IE_WLC_SHARD_INDEX") or "0")
    except ValueError:
        count, index = 1, 0
    chunks = [
        "# Generated from NetBox. Do not commit this file.",
        "# max_repetitions=10, retries=1, staggered offsets. See docs/health-metrics.md.",
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
        if auth["version"] == 2 and not auth.get("community"):
            continue
        if auth["version"] == 3 and not auth.get("user"):
            continue
        tags = {
            "wlc": str(labels.get("__meta_netbox_name") or ip),
            "site": str(labels.get("__meta_netbox_site_name") or ""),
            "platform": platform or kind,
            "role": role or "wireless-controller",
        }
        for name in wanted:
            spec = tables.get(name)
            if not spec:
                continue
            chunks.append(_input("udp://%s:161" % ip, kind, name, spec, tags, auth))
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
