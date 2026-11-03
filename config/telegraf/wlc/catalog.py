#!/usr/bin/env python3
"""9800 MDT paths and AireOS SNMP columns.

XPaths were checked against YangModels/yang vendor/cisco/xe/17151
(IOS-XE 17.15.1). A path that is not in that tree is not generated.
wireless-site-oper and wireless-ha-oper are not in 17.15.1. Site, policy
and RF tags are leaves under capwap-data tag-info. SSO state is
Cisco-IOS-XE-ha-oper (prefix ha-ios-xe-oper).

SNMP never walks a per-client table. bsnMobileStationTable and
bsnMobileStationStatsTable are not rendered. Client RSSI, SNR, rates,
retries, bytes, VLAN and mobility come from 9800 MDT only.

Per-client Prometheus series are stored by default. IE_WLC_STORE_CLIENTS=0
drops those series in Telegraf and keeps the per-AP / per-radio / per-SSID
rollups. The controller still pushes the client subscriptions until those
blocks are removed from the paste config.
"""

from __future__ import annotations

YANG_RELEASE = "17.15.1"
YANG_TREE = "vendor/cisco/xe/17151"

# Individual-client SNMP tables. Render and the snmpsim fixture must not use them.
CLIENT_WALK_PREFIXES = (
    "1.3.6.1.4.1.14179.2.1.4",  # bsnMobileStationTable
    "1.3.6.1.4.1.14179.2.1.6",  # bsnMobileStationStatsTable
)

# (offset, xpath, alias, policy, seconds, what it shows)
# policy is "periodic" or "on-change".
MDT_SUBS = (
    (0, "/wireless-access-point-oper:access-point-oper-data/ap-name-mac-map",
     "ie_wlc_ap_name_map", "periodic", 600, "AP name, radio MAC, Ethernet MAC"),
    # capwap-data and radio-oper-data reject on-change on IOS-XE ("Format failure"
    # / "on-change not supported, only periodic"). The periodic subscriptions cover them.
    (2, "/wireless-access-point-oper:access-point-oper-data/capwap-data",
     "ie_wlc_ap_mdt", "periodic", 600, "AP name, model, serial, IP, location, country, IOS, mode, tags"),
    (4, "/wireless-access-point-oper:access-point-oper-data/radio-oper-data",
     "ie_wlc_radio_mdt", "periodic", 120, "Radio channel, width, tx power, admin/oper, antenna"),
    (5, "/wireless-access-point-oper:access-point-oper-data/radio-oper-stats",
     "ie_wlc_radio_stats", "periodic", 120, "Radio retries, FCS errors, frame counts"),
    (6, "/wireless-access-point-oper:access-point-oper-data/ethernet-if-stats",
     "ie_wlc_ethernet", "periodic", 600, "AP ethernet interface packets and oper state"),
    (7, "/wireless-access-point-oper:access-point-oper-data/cdp-cache-data",
     "ie_wlc_cdp_mdt", "periodic", 600, "CDP neighbour switch, port, platform"),
    (8, "/wireless-access-point-oper:access-point-oper-data/lldp-neigh",
     "ie_wlc_lldp_mdt", "periodic", 600, "LLDP neighbour system and port"),
    (9, "/wireless-access-point-oper:access-point-oper-data/ssid-counters",
     "ie_wlc_ssid", "periodic", 120, "Clients, bytes and channel util per SSID"),
    (10, "/wireless-access-point-oper:access-point-oper-data/ssid-counters",
     "ie_wlc_ssid", "on-change", 0, "Client association count changes"),
    (11, "/wireless-access-point-oper:access-point-oper-data/capwap-pkts",
     "ie_wlc_capwap_pkts", "periodic", 120, "CAPWAP control, data and error packets"),
    (12, "/wireless-access-point-oper:access-point-oper-data/ap-image-prepare-location",
     "ie_wlc_ap_image", "periodic", 600, "AP image prepare state"),
    (13, "/wireless-access-point-oper:access-point-oper-data/predownload-data",
     "ie_wlc_ap_image", "periodic", 600, "AP image predownload state"),
    (14, "/wireless-rrm-oper:rrm-oper-data/rrm-measurement",
     "ie_wlc_rrm", "periodic", 120, "Channel util, noise, non-wifi interference, client count"),
    (15, "/wireless-rrm-oper:rrm-oper-data/radio-slot",
     "ie_wlc_rrm_slot", "periodic", 120, "RRM radio slot, neighbour and rogue counts"),
    (16, "/wireless-client-oper:client-oper-data/common-oper-data",
     "ie_wlc_client_common", "periodic", 60, "Client AP, slot, WLAN, co-state"),
    (17, "/wireless-client-oper:client-oper-data/dot11-oper-data",
     "ie_wlc_client_dot11", "periodic", 60, "Client SSID, BSSID, channel, protocol"),
    (18, "/wireless-client-oper:client-oper-data/traffic-stats",
     "ie_wlc_client_raw", "periodic", 60, "Client RSSI, SNR, rates, retries, bytes"),
    (19, "/wireless-client-oper:client-oper-data/mobility-oper-data",
     "ie_wlc_client_mobility", "periodic", 60, "Client mobility role and roam type"),
    (20, "/wireless-client-oper:client-oper-data/policy-data",
     "ie_wlc_client_policy", "periodic", 60, "Client VLAN from policy"),
    (21, "/wireless-ap-global-oper:ap-global-oper-data/ewlc-ap-stats",
     "ie_wlc_ap_global", "periodic", 600, "Controller AP counters"),
    (22, "/wireless-ap-global-oper:ap-global-oper-data/ap-join-stats",
     "ie_wlc_ap_join", "periodic", 300, "Per-AP join and disconnect reason"),
    (24, "/wireless-ap-global-oper:ap-global-oper-data/ap-history",
     "ie_wlc_ap_history", "periodic", 300, "Per-AP disconnect counter"),
    (25, "/wireless-ap-global-oper:ap-global-oper-data/emltd-join-count-stat",
     "ie_wlc_ap_global", "periodic", 300, "Joined AP count"),
    (26, "/wireless-ap-global-oper:ap-global-oper-data/wlan-client-stats",
     "ie_wlc_wlan_mdt", "periodic", 60, "Clients per WLAN (count, not a client list)"),
    (27, "/wireless-wlan-global-oper:wlan-global-oper-data/wlan-info",
     "ie_wlc_wlan_mdt", "periodic", 600, "SSID profile name and current client count"),
    (28, "/wireless-mobility-oper:mobility-oper-data/mobility-global-stats",
     "ie_wlc_mobility", "periodic", 300, "Mobility global counters"),
    (29, "/wireless-rogue-oper:rogue-oper-data/rogue-stats",
     "ie_wlc_rogue_mdt", "periodic", 300, "Rogue AP and rogue client counts"),
    (30, "/ha-ios-xe-oper:ha-oper-data/ha-infra",
     "ie_wlc_ha", "on-change", 0, "SSO HA state change"),
    (31, "/ha-ios-xe-oper:ha-oper-data/ha-infra",
     "ie_wlc_ha", "periodic", 300, "SSO HA state"),
    (32, "/process-cpu-ios-xe-oper:cpu-usage/cpu-utilization",
     "ie_wlc_cpu", "periodic", 60, "Controller CPU busy percent"),
    (33, "/memory-ios-xe-oper:memory-statistics/memory-statistic",
     "ie_wlc_memory", "periodic", 60, "Controller memory pools"),
    (34, "/environment-ios-xe-oper:environment-sensors/environment-sensor",
     "ie_wlc_env", "periodic", 60, "Temperature, fan and power sensors"),
    (35, "/platform-sw-ios-xe-oper:cisco-platform-software/system-usages",
     "ie_wlc_platform", "periodic", 120, "Platform CPU and memory usage"),
    (36, "/interfaces-ios-xe-oper:interfaces/interface",
     "ie_wlc_interface", "periodic", 120, "Controller interface counters"),
    (37, "/device-hardware-xe-oper:device-hardware-data/device-hardware",
     "ie_wlc_hardware", "periodic", 600, "Chassis hardware inventory"),
)

# Not subscribed on purpose.
SKIPPED_PATHS = (
    ("Cisco-IOS-XE-wireless-site-oper", "not in YangModels xe/17151; tags are inside capwap-data"),
    ("Cisco-IOS-XE-wireless-ha-oper", "not in YangModels xe/17151; SSO is Cisco-IOS-XE-ha-oper"),
    ("/wireless-wlan-cfg:wlan-cfg-data", "configuration tree includes key-management leaves; SSID names come from wlan-global-oper"),
    ("/wireless-rogue-oper:rogue-oper-data/rogue-data", "per-rogue AP list; rogue-stats is the count"),
    ("/wireless-rogue-oper:rogue-oper-data/rogue-client-data", "per-rogue client list"),
    ("/process-cpu-ios-xe-oper:cpu-usage/cpu-utilization/cpu-usage-processes", "per-process CPU; only the chassis total is subscribed"),
)


def mdt_aliases() -> list[tuple[str, str]]:
    """Telegraf measurement alias, encoding path. Keys are unique (TOML map)."""
    seen = []
    found = set()
    used = set()
    for _offset, xpath, alias, _policy, _seconds, _shows in MDT_SUBS:
        encoding = xpath[1:] if xpath.startswith("/") else xpath
        encoding = _encoding_path(encoding)
        if encoding in found:
            continue
        found.add(encoding)
        key = alias
        if key in used:
            key = alias + "_" + encoding.rsplit("/", 1)[-1].replace("-", "_")
        used.add(key)
        seen.append((key, encoding))
    return seen


def _encoding_path(xpath: str) -> str:
    """IOS-XE dial-out encoding paths use the module name, not the prefix."""
    module = {
        "wireless-access-point-oper:": "Cisco-IOS-XE-wireless-access-point-oper:",
        "wireless-rrm-oper:": "Cisco-IOS-XE-wireless-rrm-oper:",
        "wireless-client-oper:": "Cisco-IOS-XE-wireless-client-oper:",
        "wireless-ap-global-oper:": "Cisco-IOS-XE-wireless-ap-global-oper:",
        "wireless-wlan-global-oper:": "Cisco-IOS-XE-wireless-wlan-global-oper:",
        "wireless-mobility-oper:": "Cisco-IOS-XE-wireless-mobility-oper:",
        "wireless-rogue-oper:": "Cisco-IOS-XE-wireless-rogue-oper:",
        "ha-ios-xe-oper:": "Cisco-IOS-XE-ha-oper:",
        "process-cpu-ios-xe-oper:": "Cisco-IOS-XE-process-cpu-oper:",
        "memory-ios-xe-oper:": "Cisco-IOS-XE-memory-oper:",
        "environment-ios-xe-oper:": "Cisco-IOS-XE-environment-oper:",
        "platform-sw-ios-xe-oper:": "Cisco-IOS-XE-platform-software-oper:",
        "interfaces-ios-xe-oper:": "Cisco-IOS-XE-interfaces-oper:",
        "device-hardware-xe-oper:": "Cisco-IOS-XE-device-hardware-oper:",
    }
    for prefix, full in module.items():
        if xpath.startswith(prefix):
            return full + xpath[len(prefix):]
    return xpath


def subscription_policy(policy: str, seconds: int) -> str:
    if policy == "on-change":
        return "on-change"
    # IOS-XE periodic unit is centiseconds.
    return "periodic %d" % (int(seconds) * 100)


def wlc_subscription_base(name: str) -> int:
    """80 ids per controller, clear of the cEdge block at 60000."""
    import zlib
    slot = zlib.crc32((name or "wlc").encode("utf-8")) % 2000
    return 100000 + slot * 80


# AireOS Telegraf tables. Counts and inventory only. No client list.
# (name, oid, is_tag)
AIREOS_TABLES = {
    "inventory": {
        "measurement": "ie_wlc_ap",
        "interval": "10m",
        "offset": "0s",
        "timeout": "180s",
        "shows": "AP name, model, serial, IP, Ethernet MAC, location, mode, IOS, admin/oper",
        "fields": [
            ("ap_name", "1.3.6.1.4.1.14179.2.2.1.1.3", True),
            ("location", "1.3.6.1.4.1.14179.2.2.1.1.4", True),
            ("ap_mode", "1.3.6.1.4.1.14179.2.2.1.1.5", False),
            ("oper_status", "1.3.6.1.4.1.14179.2.2.1.1.6", False),
            ("ios_version", "1.3.6.1.4.1.14179.2.2.1.1.8", True),
            ("model", "1.3.6.1.4.1.14179.2.2.1.1.16", True),
            ("serial", "1.3.6.1.4.1.14179.2.2.1.1.17", True),
            ("ip", "1.3.6.1.4.1.14179.2.2.1.1.19", True),
            ("ios", "1.3.6.1.4.1.14179.2.2.1.1.31", True),
            ("ethernet_mac", "1.3.6.1.4.1.14179.2.2.1.1.33", True),
            ("admin_status", "1.3.6.1.4.1.14179.2.2.1.1.37", False),
        ],
    },
    "radio": {
        "measurement": "ie_wlc_radio",
        "interval": "2m",
        "offset": "20s",
        "timeout": "180s",
        "shows": "Radio type, channel, tx power level, antenna gain, admin/oper, users",
        "fields": [
            ("radio_type", "1.3.6.1.4.1.14179.2.2.2.1.2", False),
            ("channel", "1.3.6.1.4.1.14179.2.2.2.1.4", False),
            ("tx_power_level", "1.3.6.1.4.1.14179.2.2.2.1.6", False),
            ("radio_oper", "1.3.6.1.4.1.14179.2.2.2.1.12", False),
            ("clients", "1.3.6.1.4.1.14179.2.2.2.1.15", False),
            ("antenna_gain", "1.3.6.1.4.1.14179.2.2.2.1.20", False),
            ("radio_admin", "1.3.6.1.4.1.14179.2.2.2.1.34", False),
        ],
    },
    "txpower": {
        "measurement": "ie_wlc_radio",
        "interval": "2m",
        "offset": "35s",
        "timeout": "180s",
        "shows": "bsnAPIfDot11PhyTxPowerTable level-1 dBm (maximum power)",
        "fields": [
            ("tx_power_dbm", "1.3.6.1.4.1.14179.2.2.8.1.2", False),
        ],
    },
    "rf": {
        "measurement": "ie_wlc_radio",
        "interval": "2m",
        "offset": "50s",
        "timeout": "180s",
        "shows": "Channel utilization, rx load, clients per radio, poor-SNR client count",
        "fields": [
            ("rx_util", "1.3.6.1.4.1.14179.2.2.13.1.1", False),
            ("channel_util", "1.3.6.1.4.1.14179.2.2.13.1.3", False),
            ("clients", "1.3.6.1.4.1.14179.2.2.13.1.4", False),
            ("poor_snr_clients", "1.3.6.1.4.1.14179.2.2.13.1.24", False),
        ],
    },
    "noise": {
        "measurement": "ie_wlc_noise",
        "interval": "2m",
        "offset": "70s",
        "timeout": "240s",
        "shows": "bsnAPIfChannelNoiseInfoTable, collapsed to the worst dBm per radio",
        "fields": [
            ("noise_channel", "1.3.6.1.4.1.14179.2.2.15.1.1", False),
            ("noise", "1.3.6.1.4.1.14179.2.2.15.1.21", False),
        ],
    },
    "interference": {
        "measurement": "ie_wlc_interference",
        "interval": "2m",
        "offset": "90s",
        "timeout": "240s",
        "shows": "bsnAPIfChannelInterferenceInfoTable, collapsed to the worst percent per radio",
        "fields": [
            ("interference_channel", "1.3.6.1.4.1.14179.2.2.14.1.1", False),
            ("interference_power", "1.3.6.1.4.1.14179.2.2.14.1.2", False),
            ("interference", "1.3.6.1.4.1.14179.2.2.14.1.22", False),
        ],
    },
    "cdp": {
        "measurement": "ie_wlc_cdp",
        "interval": "10m",
        "offset": "120s",
        "timeout": "180s",
        "shows": "clcCdpApCacheTable neighbour switch and port (CISCO-LWAPP-CDP-MIB)",
        "fields": [
            ("ap_name", "1.3.6.1.4.1.9.9.623.1.3.1.1.2", True),
            ("neighbor_switch", "1.3.6.1.4.1.9.9.623.1.3.1.1.6", True),
            ("neighbor_port", "1.3.6.1.4.1.9.9.623.1.3.1.1.9", True),
        ],
    },
    "wlan": {
        "measurement": "ie_wlc_wlan",
        "interval": "5m",
        "offset": "30s",
        "timeout": "60s",
        "shows": "SSID name, admin state, client count per WLAN",
        "fields": [
            ("ssid", "1.3.6.1.4.1.14179.2.1.1.1.2", True),
            ("admin_status", "1.3.6.1.4.1.14179.2.1.1.1.6", False),
            ("clients", "1.3.6.1.4.1.14179.2.1.1.1.38", False),
        ],
    },
    "rogue": {
        "measurement": "ie_wlc_rogue_raw",
        "interval": "10m",
        "offset": "180s",
        "timeout": "180s",
        "shows": "Rogue AP index only; Telegraf exports one count per controller",
        "fields": [
            ("rogue_present", "1.3.6.1.4.1.14179.2.1.7.1.1", False),
        ],
    },
    "joins": {
        "measurement": "ie_wlc_join",
        "interval": "5m",
        "offset": "100s",
        "timeout": "180s",
        "shows": "cLApUpTime plus reassoc and association-failure counters",
        "fields": [
            ("ap_name", "1.3.6.1.4.1.9.9.513.1.1.1.1.5", True),
            ("uptime_centiseconds", "1.3.6.1.4.1.9.9.513.1.1.1.1.6", False),
            ("reassoc_ok", "1.3.6.1.4.1.9.9.513.1.1.1.1.67", False),
            ("reassoc_fail", "1.3.6.1.4.1.9.9.513.1.1.1.1.68", False),
            ("assoc_fail", "1.3.6.1.4.1.9.9.513.1.1.1.1.75", False),
        ],
    },
}

# snmp-exporter scalars. Not per-AP and not per-client.
SNMP_SCALARS = (
    ("9800", "cLApGlobalAPConnectCount", "1.3.6.1.4.1.9.9.513.1.3.35", "Joined AP count"),
    ("9800", "cLMobilityExtMCTotalClientCount", "1.3.6.1.4.1.9.9.846.1.1.4.13", "Total clients on the controller"),
    ("9800", "cRFStatusUnitState", "1.3.6.1.4.1.9.9.176.1.1.2", "HA unit state (active is 7)"),
    ("9800", "cRFStatusPeerUnitState", "1.3.6.1.4.1.9.9.176.1.1.4", "HA peer unit state"),
    ("aireos", "agentCurrentCPUUtilization", "1.3.6.1.4.1.14179.1.1.5.1", "Controller CPU percent"),
    ("aireos", "agentTotalMemory", "1.3.6.1.4.1.14179.1.1.5.2", "Controller RAM total, kilobytes"),
    ("aireos", "agentFreeMemory", "1.3.6.1.4.1.14179.1.1.5.3", "Controller RAM free, kilobytes"),
    ("aireos", "agentSwitchInfoPowerSupply1Present", "1.3.6.1.4.1.14179.1.1.3.2", "PSU 1 present"),
    ("aireos", "agentSwitchInfoPowerSupply1Operational", "1.3.6.1.4.1.14179.1.1.3.3", "PSU 1 operational"),
    ("aireos", "agentSwitchInfoPowerSupply2Present", "1.3.6.1.4.1.14179.1.1.3.4", "PSU 2 present"),
    ("aireos", "agentSwitchInfoPowerSupply2Operational", "1.3.6.1.4.1.14179.1.1.3.5", "PSU 2 operational"),
    ("aireos", "bsnGlobalDot11SystemMobileStations", "1.3.6.1.4.1.14179.2.3.5.1.1", "Total clients on the controller"),
    ("aireos", "agentRadioUpDownTrapCount", "1.3.6.1.4.1.14179.1.1.2.5", "Radio up/down trap counter"),
    ("aireos", "agentApAssociateDisassociateTrapCount", "1.3.6.1.4.1.14179.1.1.2.6", "AP join/disassoc trap counter"),
    ("aireos", "cRFStatusUnitState", "1.3.6.1.4.1.9.9.176.1.1.2", "HA unit state (active is 7)"),
    ("aireos", "cRFStatusPeerUnitState", "1.3.6.1.4.1.9.9.176.1.1.4", "HA peer unit state"),
)


def contains_client_walk(text: str) -> bool:
    for prefix in CLIENT_WALK_PREFIXES:
        if prefix in text:
            return True
    return False


def estimate_series(aps: int = 5000, radios_per_ap: int = 2, ssids_per_radio: int = 8,
                    clients_per_ap: int = 15, store_clients: bool = True) -> dict:
    """Prometheus series and MDT payload for one controller.

    clients_per_ap is an assumption (15). A busier controller scales the
    client term linearly. Labels do not add series until a label value changes.
    """
    radios = aps * radios_per_ap
    clients = aps * clients_per_ap
    client_fields = 8  # rssi, snr, bytes_rx, bytes_tx, tx_retries, rts_retries, current_rate, speed
    per_client = clients * client_fields if store_clients else 0
    rollup = radios * 5
    ssid = radios * ssids_per_radio
    ap_series = aps * 5  # info, oper_up, admin, uptime, disconnects
    radio_series = radios * 10
    neighbor = aps
    ethernet = aps * 2 * 3
    controller = 40
    total = per_client + rollup + ssid + ap_series + radio_series + neighbor + ethernet + controller
    # Rough kvgpb sizes. Client detail is pushed even when Prometheus drops it.
    client_bps = clients * 450 / 60.0
    radio_bps = radios * 350 / 120.0
    inventory_bps = aps * 800 / 600.0
    other_bps = 20 * 1024
    payload_bps = client_bps + radio_bps + inventory_bps + other_bps
    return {
        "aps": aps,
        "clients": clients,
        "store_clients": store_clients,
        "per_client_series": per_client,
        "rollup_series": rollup,
        "ssid_series": ssid,
        "series": total,
        "mdt_bytes_per_sec": int(payload_bps),
        "mdt_megabits_per_sec": round(payload_bps * 8 / 1_000_000, 2),
    }


def iosxe_wlc_config(name: str, ip: str, receiver: str, port: int, username: str, vrf: str = "") -> str:
    base = wlc_subscription_base(name)
    user = username or "<SNMP_V3_USERNAME>"
    lines = [
        "! Generated by InsightEngine for %s. Paste on the device." % name,
        "! InsightEngine does not push this configuration.",
        "! YANG tree %s (%s)." % (YANG_TREE, YANG_RELEASE),
        "! wireless-site-oper and wireless-ha-oper are not in that tree.",
        "! Site, policy and RF tags are inside capwap-data. SSO is Cisco-IOS-XE-ha-oper.",
        "! wireless-wlan-cfg is not subscribed (key-management leaves). SSID names are wlan-global-oper.",
        "! Per-client series are stored unless IE_WLC_STORE_CLIENTS=0 on telegraf-wlc.",
        "! That switch does not stop the dial-out. Delete the client-oper blocks to stop the bandwidth.",
        "! SNMP below is names and placeholders. Secrets are not in this text.",
        "! source-vrf %s" % (vrf if vrf else "is omitted. The management address is in the global table."),
        "! A management VRF is added only when the device has one set. Mgmt-intf is not the default.",
        "! capwap-data, radio-oper-data and ap-join-stats are periodic only.",
        "! This IOS-XE rejects on-change for those three paths.",
        "! Replace %s if IE_MDT_RECEIVER was unset." % receiver,
        "!",
        "netconf-yang",
        "!",
        "snmp-server view IE-READ iso included",
        "snmp-server group IE-READ v3 priv read IE-READ",
        "snmp-server user %s IE-READ v3 auth sha <auth-passphrase> priv aes 256 <priv-passphrase>" % user,
        "! v2c community string is the ie_wlc_v2 secret. It is not written here.",
        "! snmp-server community <ie_wlc_v2 community> RO",
        "!",
    ]
    for offset, xpath, _alias, policy, seconds, shows in MDT_SUBS:
        lines.append("! %s" % shows)
        block = [
            "telemetry ietf subscription %d" % (base + offset),
            " encoding encode-kvgpb",
            " filter xpath %s" % xpath,
            " source-address %s" % ip,
        ]
        if vrf:
            block.append(" source-vrf %s" % vrf)
        block.extend([
            " stream yang-push",
            " update-policy %s" % subscription_policy(policy, seconds),
            " receiver ip address %s %d protocol grpc-tcp" % (receiver, port),
        ])
        lines.extend(block)
        lines.append("!")
    lines.extend([
        "! Verify after paste:",
        "! show telemetry ietf subscription all",
        "! show telemetry connection all",
        "! show telemetry internal subscription all",
        "! show telemetry internal connection",
        "! show telemetry ietf subscription %d receiver" % base,
    ])
    return "\n".join(lines).rstrip() + "\n"


def aireos_snmp_config(name: str, username: str) -> str:
    user = username or "<SNMP_V3_USERNAME>"
    lines = [
        "! Generated by InsightEngine for %s. Paste on the AireOS controller." % name,
        "! InsightEngine does not push this configuration.",
        "! AireOS has no model-driven telemetry. This is SNMP only.",
        "! Per-client tables (bsnMobileStation) are not polled. Client counts only.",
        "! The community string and the v3 passwords are secrets. They are not in this text.",
        "! <ie_wlc_v2> is the credential name. Type the community when the controller asks,",
        "! or replace <ie_wlc_v2> with that name and enter the secret out of band.",
        "!",
        "config snmp version v1 disable",
        "config snmp version v2c enable",
        "config snmp version v3 enable",
        "config snmp community create <ie_wlc_v2>",
        "config snmp community mode enable <ie_wlc_v2>",
        "config snmp community accessmode ro <ie_wlc_v2>",
        "config snmp v3user create %s ro hmacsha aescfb128 <auth-passphrase> <priv-passphrase>" % user,
        "! InsightEngine does not use SNMP traps. Leave this commented.",
        "! config snmp trapreceiver create <collector-ip> <ie_wlc_v2>",
        "!",
        "! Verify:",
        "show snmpcommunity",
        "show snmpversion",
        "show snmpv3user",
        "show trapflags",
    ]
    return "\n".join(lines).rstrip() + "\n"


def snmp_username(env: dict) -> str:
    return (env.get("SNMP_V3_USERNAME") or env.get("SNMP_V3_USER") or "").strip()


def sample_kvgpb() -> list[dict]:
    """One dial-out content sample per encoding path, for mdt_send and tests."""
    samples = []
    seen = set()
    for _offset, xpath, _alias, policy, _seconds, _shows in MDT_SUBS:
        encoding = _encoding_path(xpath[1:] if xpath.startswith("/") else xpath)
        if encoding in seen:
            continue
        seen.add(encoding)
        samples.append({
            "path": encoding,
            "policy": policy,
            "keys": _sample_keys(encoding),
            "content": _sample_content(encoding),
        })
    return samples


def _sample_keys(path: str) -> list[tuple[str, str]]:
    if "common-oper-data" in path or "dot11-oper-data" in path or "traffic-stats" in path or "mobility-oper-data" in path and "wireless-client" in path:
        return [("client-mac", "aa:bb:cc:dd:ee:01")]
    if "policy-data" in path:
        return [("mac", "aa:bb:cc:dd:ee:01")]
    if path.endswith("capwap-data") or "ap-name-mac-map" in path or "capwap-pkts" in path or "ap-join-stats" in path:
        return [("wtp-mac", "00:11:22:33:44:55")]
    if "radio-oper" in path or "rrm-" in path or "ssid-counters" in path or "ethernet-if" in path:
        return [("wtp-mac", "00:11:22:33:44:55"), ("radio-slot-id", "1")]
    if "cdp-cache" in path:
        return [("mac-addr", "00:11:22:33:44:55"), ("cdp-cache-device-id", "sw-edge")]
    if "lldp-neigh" in path:
        return [("wtp-mac", "00:11:22:33:44:55"), ("system-name", "sw-edge")]
    if "wlan-info" in path or "wlan-client-stats" in path:
        return [("wlan-id", "1")]
    if "ha-infra" in path:
        return [("chassis", "local")]
    if "memory-statistic" in path:
        return [("name", "processor")]
    if "environment-sensor" in path:
        return [("name", "Temp: Inlet")]
    if "interface" in path:
        return [("name", "GigabitEthernet0")]
    return [("name", "wlc")]


def _sample_content(path: str) -> list[tuple[str, str]]:
    if path.endswith("traffic-stats"):
        return [("most-recent-rssi", "-62"), ("most-recent-snr", "28"), ("bytes-rx", "1000"),
                ("bytes-tx", "2000"), ("tx-retries", "3"), ("current-rate", "144"), ("speed", "144")]
    if path.endswith("common-oper-data"):
        return [("ap-name", "AP-1"), ("ms-ap-slot-id", "1"), ("wlan-id", "1")]
    if path.endswith("dot11-oper-data"):
        return [("vap-ssid", "corp"), ("ms-ap-slot-id", "1"), ("radio-type", "dot11ax-5ghz"),
                ("ewlc-ms-phy-type", "ax"), ("current-channel", "36")]
    if "client-oper-data/mobility-oper-data" in path:
        return [("mm-client-role", "local"), ("mm-client-roam-type", "none")]
    if path.endswith("policy-data"):
        return [("res-vlan-id", "20"), ("res-vlan-name", "users")]
    if path.endswith("capwap-data"):
        # Cisco-IOS-XE-wireless-access-point-oper 17.15.1 grouping capwap-wtp-data.
        # kvgpb nests containers; Telegraf names the leaves with slash prefixes.
        return [
            ("name", "AP-1"),
            ("ip-addr", "10.8.0.10"),
            ("wtp-ip", "10.8.0.10"),
            ("country-code", "ZA"),
            ("device-detail", [
                ("static-info", [
                    ("board-data", [
                        ("wtp-serial-num", "FGL2417ABC1"),
                        ("wtp-enet-mac", "00:11:22:33:44:66"),
                    ]),
                    ("ap-models", [
                        ("model", "C9120AXI-B"),
                    ]),
                ]),
                ("wtp-version", [
                    ("sw-version", "17.15.1.4"),
                ]),
            ]),
            ("ap-location", [
                ("location", "floor-1"),
                ("floor", "2"),
            ]),
            ("tag-info", [
                ("site-tag", [("site-tag-name", "site-a")]),
                ("policy-tag-info", [("policy-tag-name", "pol-a")]),
                ("rf-tag", [("rf-tag-name", "rf-a")]),
            ]),
            ("ap-state", [
                ("ap-operation-state", "ap-up"),
            ]),
            ("ap-mode-data", [
                ("wtp-mode", "local"),
            ]),
        ]
    if "radio-oper-data" in path and "rrm" not in path:
        return [("radio-type", "radio-80211a"), ("admin-state", "enabled"), ("oper-state", "up"),
                ("curr-freq", "36"), ("chan-width", "40"), ("current-tx-power-level", "1"),
                ("curr-tx-power-in-dbm", "18"), ("antenna-gain", "4")]
    if path.endswith("rrm-measurement"):
        return [("cca-util-percentage", "55"), ("rx-noise-channel-utilization", "12"),
                ("non-wifi-inter", "8"), ("stations", "4")]
    if path.endswith("radio-slot"):
        return [("rogue-20-count", "1"), ("chan-width", "40")]
    if path.endswith("ssid-counters"):
        return [("vap-ssid", "corp"), ("num-assoc-clients", "4"), ("bss-chan-util", "20"), ("radio-band", "5")]
    if "cdp-cache" in path:
        return [("ap-name", "AP-1"), ("cdp-cache-device-port", "Gi1/0/7"), ("cdp-cache-platform", "C9300")]
    if "lldp-neigh" in path:
        return [("system-name", "sw-edge"), ("port-id", "Gi1/0/7"), ("local-port", "wired0")]
    if path.endswith("rogue-stats"):
        return [("total-count", "3"), ("malicious-count", "1"), ("friendly-count", "2")]
    if "ha-infra" in path:
        return [("ha-state", "active"), ("peer-state", "standby-hot")]
    if path.endswith("cpu-utilization"):
        return [("five-seconds", "7"), ("five-minutes", "6")]
    if "memory-statistic" in path:
        return [("total-memory", "8000000"), ("used-memory", "3000000"), ("free-memory", "5000000")]
    if "emltd-join-count" in path or path.endswith("ewlc-ap-stats"):
        return [("joined-aps-count", "2")]
    if "wlan" in path:
        return [("wlan-profile", "corp"), ("curr-clients-count", "4")]
    if "ap-join-stats" in path or "ap-history" in path:
        return [("ap-disconnect-reason", "none"), ("disconnects", "0"), ("reboot-reason", "none")]
    if "ethernet" in path:
        return [("if-name", "wired0"), ("rx-pkts", "10"), ("tx-pkts", "12")]
    if "capwap-pkts" in path:
        return [("cntrl-pkts", "5"), ("capwap-error-pkts", "0")]
    if "environment" in path:
        return [("current-reading", "37"), ("sensor-name", "inlet")]
    return [("value", "1")]


def snmprec_fixture() -> str:
    """One AireOS AP, WLAN count, rogue index, and controller scalars. No client rows."""
    mac = "0.17.34.1.2.3"
    slot = mac + ".0"
    lines = [
        ("1.3.6.1.4.1.14179.2.2.1.1.3." + mac, "4x", "61702d31"),  # ap-1
        ("1.3.6.1.4.1.14179.2.2.1.1.4." + mac, "4", "floor-1"),
        ("1.3.6.1.4.1.14179.2.2.1.1.6." + mac, "2", "1"),
        ("1.3.6.1.4.1.14179.2.2.1.1.16." + mac, "4", "AIR-CAP3702"),
        ("1.3.6.1.4.1.14179.2.2.1.1.17." + mac, "4", "FGL00001"),
        ("1.3.6.1.4.1.14179.2.2.1.1.19." + mac, "4", "10.8.0.10"),
        ("1.3.6.1.4.1.14179.2.2.2.1.4." + slot, "2", "36"),
        ("1.3.6.1.4.1.14179.2.2.2.1.6." + slot, "2", "1"),
        ("1.3.6.1.4.1.14179.2.2.13.1.3." + slot, "2", "22"),
        ("1.3.6.1.4.1.14179.2.2.13.1.4." + slot, "2", "4"),
        ("1.3.6.1.4.1.14179.2.2.15.1.21." + slot + ".36", "2", "-92"),
        ("1.3.6.1.4.1.14179.2.2.14.1.22." + slot + ".36", "2", "5"),
        ("1.3.6.1.4.1.14179.2.1.1.1.2.1", "4", "corp"),
        ("1.3.6.1.4.1.14179.2.1.1.1.38.1", "65", "4"),
        ("1.3.6.1.4.1.14179.2.1.7.1.1.0.1.2.3.4.5", "4x", "000102030405"),
        ("1.3.6.1.4.1.14179.2.3.5.1.1.0", "2", "4"),
        ("1.3.6.1.4.1.14179.1.1.5.1.0", "2", "11"),
        ("1.3.6.1.4.1.14179.1.1.5.3.0", "2", "500000"),
        ("1.3.6.1.4.1.9.9.513.1.3.35.0", "65", "1"),
        ("1.3.6.1.4.1.9.9.846.1.1.4.13.0", "65", "4"),
        ("1.3.6.1.4.1.9.9.176.1.1.2.0", "2", "7"),
        ("1.3.6.1.4.1.9.9.623.1.3.1.1.2.1", "4", "ap-1"),
        ("1.3.6.1.4.1.9.9.623.1.3.1.1.6.1", "4", "sw-edge"),
        ("1.3.6.1.4.1.9.9.623.1.3.1.1.9.1", "4", "Gi1/0/7"),
    ]
    rendered = ["%s|%s|%s" % item for item in lines]
    rendered.sort(key=lambda row: tuple(int(part) for part in row.split("|", 1)[0].split(".") if part))
    return "\n".join(rendered) + "\n"
