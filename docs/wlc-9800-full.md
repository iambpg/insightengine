# Catalyst 9800 and AireOS collection

InsightEngine collects wireless data and does not push configuration. The device page **Controller config** button and `GET /api/v1/devices/{id}/telemetry-config` return text to paste. `pushed` is false.

XPaths were checked against YangModels `vendor/cisco/xe/17151` (IOS-XE 17.15.1). `Cisco-IOS-XE-wireless-site-oper` and `Cisco-IOS-XE-wireless-ha-oper` are not in that tree. Site, policy and RF tags are under `capwap-data`. SSO state is `Cisco-IOS-XE-ha-oper` (`ha-ios-xe-oper`). `wireless-wlan-cfg` is not subscribed because that configuration tree includes key-management leaves. SSID names and client counts come from `wlan-global-oper`. Rogue collection is the `rogue-stats` counts, not the per-rogue list.

## Clients

SNMP does not walk individual clients. `bsnMobileStationTable` and `bsnMobileStationStatsTable` are not rendered for AireOS or for a 9800. SNMP collects client **counts**: per radio (`bsnAPIfLoadNumOfClients`, `bsnApIfNoOfUsers`), per WLAN (`bsnDot11EssNumberOfMobileStations`), and the controller total (`bsnGlobalDot11SystemMobileStations` on AireOS, `cLMobilityExtMCTotalClientCount` on 9800).

9800 MDT collects the client detail that exists in `Cisco-IOS-XE-wireless-client-oper`: AP, slot, SSID, band, protocol, VLAN, mobility role, RSSI, SNR, rates, retries and bytes. Telegraf stores one Prometheus series per numeric field per client **by default**. Set `IE_WLC_STORE_CLIENTS=0` to drop those series and keep the per-AP/per-radio rollup (`ie_wlc_client_radio_*`) and the per-SSID count (`ie_wlc_ssid_clients`). The controller still pushes the client subscriptions until those blocks are removed from the paste config. Rollups and alerts (`WifiRssiLow`, `WifiSnrLow`) use the rollup, so they keep working when per-client series are off.

AireOS has no per-client RSSI or SNR over SNMP under this rule. `bsnAPIfPoorSNRClients` is a count of clients the controller already marked as poor SNR. `WifiPoorSnrClients` uses that count. Average RSSI and SNR alerts apply where MDT has filled `ie_wlc_client_radio_*`.

## Intervals

| Path | Interval |
|---|---|
| AP inventory, CDP/LLDP, ethernet, image, hardware | 600s |
| Radio oper, RRM, SSID counters | 120s, plus on-change for channel, tx power and SSID client counts |
| Client detail and WLAN client counts | 60s |
| AP join/leave (`capwap-data`, `ap-join-stats`) and HA | on-change, with a periodic refresh |

AireOS Telegraf uses the same idea: inventory, CDP, rogue count and joins at 5–10 minutes; radio, noise, interference and client counts at 2 minutes; WLAN counts at 5 minutes.

## Cardinality and bandwidth

Assumption for the estimate: 2 radios per AP, 8 SSIDs per radio, 15 clients per AP. Change the client term linearly for a busier controller. The 5,000-AP controller is the peak; 12 controllers and about 8,500 APs are the fleet sum, not one dial-out.

| Case | Prometheus series | MDT payload |
|---|---|---|
| 5,000 APs, per-client MDT stored (default) | 890040 | 4.95 Mbit/s |
| 5,000 APs, `IE_WLC_STORE_CLIENTS=0` | 290040 | 4.95 Mbit/s (dial-out unchanged) |
| 8,500 APs across the fleet, per-client stored | 1513040 | about 8.3 Mbit/s if every controller pushed like the peak | 

Per-client series are 8 numeric fields (RSSI, SNR, bytes in, bytes out, tx retries, RTS retries, current rate, and the same rate when only `speed` is present it shares `current_rate`). Labels are client, AP, radio, SSID, band, protocol, VLAN and mobility. A mobility or VLAN change starts a new series until the old one expires (Telegraf expiration is 20 minutes).

Default export for one 5,000-AP controller is about 890040 series, of which 600000 are per client, 50000 are radio rollups and 80000 are per-SSID counts.

## 9800 MDT

| Source | Path | Interval | Shows |
|---|---|---|---|
| MDT | `/wireless-access-point-oper:access-point-oper-data/ap-name-mac-map` | 600s | AP name, radio MAC, Ethernet MAC |
| MDT | `/wireless-access-point-oper:access-point-oper-data/capwap-data` | on-change | AP join/leave, name, model, serial, IP, location, country, IOS, mode, tags |
| MDT | `/wireless-access-point-oper:access-point-oper-data/capwap-data` | 600s | AP inventory refresh |
| MDT | `/wireless-access-point-oper:access-point-oper-data/radio-oper-data` | on-change | Radio channel, width, tx power, admin/oper, antenna |
| MDT | `/wireless-access-point-oper:access-point-oper-data/radio-oper-data` | 120s | Radio oper refresh |
| MDT | `/wireless-access-point-oper:access-point-oper-data/radio-oper-stats` | 120s | Radio retries, FCS errors, frame counts |
| MDT | `/wireless-access-point-oper:access-point-oper-data/ethernet-if-stats` | 600s | AP ethernet interface packets and oper state |
| MDT | `/wireless-access-point-oper:access-point-oper-data/cdp-cache-data` | 600s | CDP neighbour switch, port, platform |
| MDT | `/wireless-access-point-oper:access-point-oper-data/lldp-neigh` | 600s | LLDP neighbour system and port |
| MDT | `/wireless-access-point-oper:access-point-oper-data/ssid-counters` | 120s | Clients, bytes and channel util per SSID |
| MDT | `/wireless-access-point-oper:access-point-oper-data/ssid-counters` | on-change | Client association count changes |
| MDT | `/wireless-access-point-oper:access-point-oper-data/capwap-pkts` | 120s | CAPWAP control, data and error packets |
| MDT | `/wireless-access-point-oper:access-point-oper-data/ap-image-prepare-location` | 600s | AP image prepare state |
| MDT | `/wireless-access-point-oper:access-point-oper-data/predownload-data` | 600s | AP image predownload state |
| MDT | `/wireless-rrm-oper:rrm-oper-data/rrm-measurement` | 120s | Channel util, noise, non-wifi interference, client count |
| MDT | `/wireless-rrm-oper:rrm-oper-data/radio-slot` | 120s | RRM radio slot, neighbour and rogue counts |
| MDT | `/wireless-client-oper:client-oper-data/common-oper-data` | 60s | Client AP, slot, WLAN, co-state |
| MDT | `/wireless-client-oper:client-oper-data/dot11-oper-data` | 60s | Client SSID, BSSID, channel, protocol |
| MDT | `/wireless-client-oper:client-oper-data/traffic-stats` | 60s | Client RSSI, SNR, rates, retries, bytes |
| MDT | `/wireless-client-oper:client-oper-data/mobility-oper-data` | 60s | Client mobility role and roam type |
| MDT | `/wireless-client-oper:client-oper-data/policy-data` | 60s | Client VLAN from policy |
| MDT | `/wireless-ap-global-oper:ap-global-oper-data/ewlc-ap-stats` | 600s | Controller AP counters |
| MDT | `/wireless-ap-global-oper:ap-global-oper-data/ap-join-stats` | 300s | Per-AP join and disconnect reason |
| MDT | `/wireless-ap-global-oper:ap-global-oper-data/ap-join-stats` | on-change | AP join/leave reason |
| MDT | `/wireless-ap-global-oper:ap-global-oper-data/ap-history` | 300s | Per-AP disconnect counter |
| MDT | `/wireless-ap-global-oper:ap-global-oper-data/emltd-join-count-stat` | 300s | Joined AP count |
| MDT | `/wireless-ap-global-oper:ap-global-oper-data/wlan-client-stats` | 60s | Clients per WLAN (count, not a client list) |
| MDT | `/wireless-wlan-global-oper:wlan-global-oper-data/wlan-info` | 600s | SSID profile name and current client count |
| MDT | `/wireless-mobility-oper:mobility-oper-data/mobility-global-stats` | 300s | Mobility global counters |
| MDT | `/wireless-rogue-oper:rogue-oper-data/rogue-stats` | 300s | Rogue AP and rogue client counts |
| MDT | `/ha-ios-xe-oper:ha-oper-data/ha-infra` | on-change | SSO HA state change |
| MDT | `/ha-ios-xe-oper:ha-oper-data/ha-infra` | 300s | SSO HA state |
| MDT | `/process-cpu-ios-xe-oper:cpu-usage/cpu-utilization` | 60s | Controller CPU busy percent |
| MDT | `/memory-ios-xe-oper:memory-statistics/memory-statistic` | 60s | Controller memory pools |
| MDT | `/environment-ios-xe-oper:environment-sensors/environment-sensor` | 60s | Temperature, fan and power sensors |
| MDT | `/platform-sw-ios-xe-oper:cisco-platform-software/system-usages` | 120s | Platform CPU and memory usage |
| MDT | `/interfaces-ios-xe-oper:interfaces/interface` | 120s | Controller interface counters |
| MDT | `/device-hardware-xe-oper:device-hardware-data/device-hardware` | 600s | Chassis hardware inventory |

## 9800 and AireOS SNMP scalars (snmp-exporter)

Controller CPU, memory, temperature, fans and PSUs on a 9800 also come from the existing modules `cisco_pro`, `cisco_enhanced_mem`, `cisco_entity_sensor`, `cisco_fru` and `cisco_env`. AireOS CPU, memory and the two PSUs are `AIRESPACE-SWITCHING-MIB`. That MIB has no temperature or fan table; fans and temperature appear only when the image answers `cisco_env` (CISCO-ENVMON-MIB). HA is `CISCO-RF-MIB` for both. There is no per-client walk in either module.

| Source | OID | Name | Shows |
|---|---|---|---|
| SNMP 9800 | `1.3.6.1.4.1.9.9.513.1.3.35` | `cLApGlobalAPConnectCount` | Joined AP count |
| SNMP 9800 | `1.3.6.1.4.1.9.9.846.1.1.4.13` | `cLMobilityExtMCTotalClientCount` | Total clients on the controller |
| SNMP 9800 | `1.3.6.1.4.1.9.9.176.1.1.2` | `cRFStatusUnitState` | HA unit state (active is 7) |
| SNMP 9800 | `1.3.6.1.4.1.9.9.176.1.1.4` | `cRFStatusPeerUnitState` | HA peer unit state |
| SNMP aireos | `1.3.6.1.4.1.14179.1.1.5.1` | `agentCurrentCPUUtilization` | Controller CPU percent |
| SNMP aireos | `1.3.6.1.4.1.14179.1.1.5.2` | `agentTotalMemory` | Controller RAM total, kilobytes |
| SNMP aireos | `1.3.6.1.4.1.14179.1.1.5.3` | `agentFreeMemory` | Controller RAM free, kilobytes |
| SNMP aireos | `1.3.6.1.4.1.14179.1.1.3.2` | `agentSwitchInfoPowerSupply1Present` | PSU 1 present |
| SNMP aireos | `1.3.6.1.4.1.14179.1.1.3.3` | `agentSwitchInfoPowerSupply1Operational` | PSU 1 operational |
| SNMP aireos | `1.3.6.1.4.1.14179.1.1.3.4` | `agentSwitchInfoPowerSupply2Present` | PSU 2 present |
| SNMP aireos | `1.3.6.1.4.1.14179.1.1.3.5` | `agentSwitchInfoPowerSupply2Operational` | PSU 2 operational |
| SNMP aireos | `1.3.6.1.4.1.14179.2.3.5.1.1` | `bsnGlobalDot11SystemMobileStations` | Total clients on the controller |
| SNMP aireos | `1.3.6.1.4.1.14179.1.1.2.5` | `agentRadioUpDownTrapCount` | Radio up/down trap counter |
| SNMP aireos | `1.3.6.1.4.1.14179.1.1.2.6` | `agentApAssociateDisassociateTrapCount` | AP join/disassoc trap counter |
| SNMP aireos | `1.3.6.1.4.1.9.9.176.1.1.2` | `cRFStatusUnitState` | HA unit state (active is 7) |
| SNMP aireos | `1.3.6.1.4.1.9.9.176.1.1.4` | `cRFStatusPeerUnitState` | HA peer unit state |

## AireOS Telegraf SNMP

| Source | Table | Interval | OID columns | Shows |
|---|---|---|---|---|
| SNMP AireOS | `inventory` | 10m | `1.3.6.1.4.1.14179.2.2.1.1.3` ap_name, `1.3.6.1.4.1.14179.2.2.1.1.4` location, `1.3.6.1.4.1.14179.2.2.1.1.5` ap_mode, `1.3.6.1.4.1.14179.2.2.1.1.6` oper_status, `1.3.6.1.4.1.14179.2.2.1.1.8` ios_version, `1.3.6.1.4.1.14179.2.2.1.1.16` model, `1.3.6.1.4.1.14179.2.2.1.1.17` serial, `1.3.6.1.4.1.14179.2.2.1.1.19` ip, `1.3.6.1.4.1.14179.2.2.1.1.31` ios, `1.3.6.1.4.1.14179.2.2.1.1.33` ethernet_mac, `1.3.6.1.4.1.14179.2.2.1.1.37` admin_status | AP name, model, serial, IP, Ethernet MAC, location, mode, IOS, admin/oper |
| SNMP AireOS | `radio` | 2m | `1.3.6.1.4.1.14179.2.2.2.1.2` radio_type, `1.3.6.1.4.1.14179.2.2.2.1.4` channel, `1.3.6.1.4.1.14179.2.2.2.1.6` tx_power_level, `1.3.6.1.4.1.14179.2.2.2.1.12` radio_oper, `1.3.6.1.4.1.14179.2.2.2.1.15` clients, `1.3.6.1.4.1.14179.2.2.2.1.20` antenna_gain, `1.3.6.1.4.1.14179.2.2.2.1.34` radio_admin | Radio type, channel, tx power level, antenna gain, admin/oper, users |
| SNMP AireOS | `txpower` | 2m | `1.3.6.1.4.1.14179.2.2.8.1.2` tx_power_dbm | bsnAPIfDot11PhyTxPowerTable level-1 dBm (maximum power) |
| SNMP AireOS | `rf` | 2m | `1.3.6.1.4.1.14179.2.2.13.1.1` rx_util, `1.3.6.1.4.1.14179.2.2.13.1.3` channel_util, `1.3.6.1.4.1.14179.2.2.13.1.4` clients, `1.3.6.1.4.1.14179.2.2.13.1.24` poor_snr_clients | Channel utilization, rx load, clients per radio, poor-SNR client count |
| SNMP AireOS | `noise` | 2m | `1.3.6.1.4.1.14179.2.2.15.1.1` noise_channel, `1.3.6.1.4.1.14179.2.2.15.1.21` noise | bsnAPIfChannelNoiseInfoTable, collapsed to the worst dBm per radio |
| SNMP AireOS | `interference` | 2m | `1.3.6.1.4.1.14179.2.2.14.1.1` interference_channel, `1.3.6.1.4.1.14179.2.2.14.1.2` interference_power, `1.3.6.1.4.1.14179.2.2.14.1.22` interference | bsnAPIfChannelInterferenceInfoTable, collapsed to the worst percent per radio |
| SNMP AireOS | `cdp` | 10m | `1.3.6.1.4.1.9.9.623.1.3.1.1.2` ap_name, `1.3.6.1.4.1.9.9.623.1.3.1.1.6` neighbor_switch, `1.3.6.1.4.1.9.9.623.1.3.1.1.9` neighbor_port | clcCdpApCacheTable neighbour switch and port (CISCO-LWAPP-CDP-MIB) |
| SNMP AireOS | `wlan` | 5m | `1.3.6.1.4.1.14179.2.1.1.1.2` ssid, `1.3.6.1.4.1.14179.2.1.1.1.6` admin_status, `1.3.6.1.4.1.14179.2.1.1.1.38` clients | SSID name, admin state, client count per WLAN |
| SNMP AireOS | `rogue` | 10m | `1.3.6.1.4.1.14179.2.1.7.1.1` rogue_present | Rogue AP index only; Telegraf exports one count per controller |
| SNMP AireOS | `joins` | 5m | `1.3.6.1.4.1.9.9.513.1.1.1.1.5` ap_name, `1.3.6.1.4.1.9.9.513.1.1.1.1.6` uptime_centiseconds, `1.3.6.1.4.1.9.9.513.1.1.1.1.67` reassoc_ok, `1.3.6.1.4.1.9.9.513.1.1.1.1.68` reassoc_fail, `1.3.6.1.4.1.9.9.513.1.1.1.1.75` assoc_fail | cLApUpTime plus reassoc and association-failure counters |

Channel width is not a column on `bsnAPIfTable`. `bsnAPIfDot11PhyTxPowerTable` level 1 (`…​2.2.8.1.2`) is the maximum dBm, and `bsnAPIfPhyTxPowerLevel` is the current level (1 is highest). Join time is not a separate AireOS column; `cLApUpTime` is the AP uptime in TimeTicks when the controller serves CISCO-LWAPP-AP-MIB. Per-AP reassociation and association-failure counters are `cLApReassocSuccCount`, `cLApReassocFailCount` and `cLApAssocFailTimes`. The controller-wide join/disassoc counter is `agentApAssociateDisassociateTrapCount`. CDP neighbours are `clcCdpApCacheTable` in CISCO-LWAPP-CDP-MIB (the table the AireOS CLI calls the AP CDP cache). The rogue walk is the MAC index only; Telegraf exports `ie_wlc_rogue_aps` and drops the per-rogue series.

## What a lab proved, and what needs a real controller

Docker and unit tests use a simulated gRPC dial-out (one kvgpb sample per path), an snmpsim walk of the AireOS count and inventory OIDs, and `promtool` on the rules. They do not prove a Catalyst 9800 or an AireOS controller.

On the first 9800, confirm `show telemetry ietf subscription all` and that `most-recent-rssi` is still on `traffic-stats` for that release. Confirm `source-vrf` is deleted when the management address is in the global table. Confirm HA state strings from `Cisco-IOS-XE-ha-oper`.

On the first AireOS controller, confirm `cLApUpTime` and the reassoc counters exist (some images only serve AIRESPACE-WIRELESS-MIB). Confirm `clcCdpApCacheTable` is populated. Confirm temperature and fans, which are not in AIRESPACE-SWITCHING-MIB. Time one noise and interference walk: those tables are indexed by channel, so the SNMP walk is wider than the Prometheus series Telegraf keeps.

