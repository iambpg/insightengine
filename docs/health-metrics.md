# Device health metrics

Every device type InsightEngine monitors is asked for the same five groups. snmp-exporter walks the controller or the box. Telegraf walks per-AP tables on the wireless controllers. Prometheus recording rules publish one set of names (`ie:…`) so Grafana and the device page do not care which vendor answered.

| Group | Recording rule | What it means |
|---|---|---|
| Interface utilization | `ie:interface_utilization_ratio` | Max of inbound and outbound bits, divided by `ifHighSpeed` |
| Interface drops | `ie:interface_drops_rate` | `ifInDiscards` + `ifOutDiscards` per second |
| Memory | `ie:device_memory_used_ratio` | Used / (used + free), or the vendor percent gauge |
| Fans | `ie:device_fan_ok` | 1 ok or warning, 0 failed. `notPresent` is omitted |
| Power | `ie:device_psu_ok` | 1 ok, 0 failed |
| Temperature | `ie:device_temperature_celsius` | Degrees C when a sensor reports units. Status-only platforms stay on the raw enum |

Critical-path interfaces are those whose `ifAlias`, `ifDescr`, or `ifName` matches `critical-path` or `uplink` (`ie:interface_critical_path`). The device page also highlights a NetBox interface tag `critical-path` or the word uplink in the name or description. Alerts (10 minutes): critical-path utilization above 80%, critical-path drops above 0. Also: fan or PSU failed (5 minutes), temperature above 75°C (10 minutes), memory above 90% (10 minutes). Rules live in `config/prometheus/health-rules.yml`.

The device page Health panel prints **not supported by this device** when that platform has no poll for the group. An empty chart is not used for that case.

## Support matrix

| Device | Interfaces | Memory | Fan | PSU | Temperature | Collector |
|---|---|---|---|---|---|---|
| Cisco Catalyst IOS (2960 / 2960X) | IF-MIB `ifHCInOctets`, `ifHCOutOctets`, `ifInDiscards`, `ifOutDiscards`, `ifInErrors`, `ifOutErrors`, `ifHighSpeed` | `CISCO-MEMORY-POOL-MIB` `ciscoMemoryPoolUsed` / `ciscoMemoryPoolFree` (processor pool, index 1) | `CISCO-ENVMON-MIB` `ciscoEnvMonFanState` | `ciscoEnvMonSupplyState` | Often status only: `ciscoEnvMonTemperatureState`. `ciscoEnvMonTemperatureStatusValue` is recorded only when it is non-zero | snmp-exporter `if_mib`, `cisco_env` (or the existing `cisco_environ`), `cisco_mem` |
| Cisco IOS-XE (Catalyst 9k, ISR, SD-WAN) | same IF-MIB | `CISCO-ENHANCED-MEMPOOL-MIB` `cempMemPoolUsed` / `cempMemPoolFree`, with `cisco_mem` as a fallback | `CISCO-ENTITY-FRU-CONTROL-MIB` `cefcFanTrayOperStatus` plus ENVMON when the box still has it | `cefcFRUPowerOperStatus` | `CISCO-ENTITY-SENSOR-MIB` `entSensorValue` where `entSensorType` is celsius (8) and scale is units (9). Name from `entPhysicalName` | snmp-exporter `if_mib`, `cisco_enhanced_mem`, `cisco_entity_sensor`, `cisco_fru`, `cisco_pro`, `cisco_env`, `cisco_mem`, `cisco_cdp`, `lldp` |
| Cisco NX-OS | same IF-MIB | enhanced mempool, classic pool as fallback | FRU fan tray | FRU power | entity sensor | snmp-exporter `if_mib`, `cisco_enhanced_mem`, `cisco_entity_sensor`, `cisco_fru`, `cisco_cdp`, `lldp`, `cisco_mem` |
| Cisco ASA | same IF-MIB | classic memory pool | ENVMON | ENVMON | ENVMON, often status | snmp-exporter `if_mib`, `cisco_env`, `cisco_mem`, `cisco_cdp`, `lldp` |
| Cisco AireOS WLC | IF-MIB on the controller | `AIRESPACE-SWITCHING-MIB` `agentTotalMemory` / `agentFreeMemory` (KB) and classic `cisco_mem` when present | No polled fan table. Fan failure is a trap. The panel says not supported | `agentSwitchInfoPowerSupply1/2Present` and `Operational`. A supply that is not present is ignored | No polled temperature table. The panel says not supported unless ENVMON returns a value | snmp-exporter `cisco_wlc_aireos` plus `if_mib`, `cisco_env`, `cisco_mem`, `cisco_pro`. Joined AP count is `count(ie_wlc_ap_oper_status)` from Telegraf, not a second copy of `bsnAPTable` |
| Cisco Catalyst 9800 (IOS-XE WLC) | IF-MIB | enhanced mempool and `CISCO-PROCESS-MIB` for CPU | FRU | FRU | entity sensor | snmp-exporter `cisco_wlc_iosxe` (`cLApGlobalAPConnectCount`, one gauge) plus the IOS-XE health modules. Per-AP rows are not in this scrape |
| Cisco AP | Not on the AP. Radio channel utilization is Telegraf on the WLC | not supported | not supported | not supported | not supported | No SNMP agent. Telegraf polls the WLC |
| FortiGate | `if_mib_fortigate` | `fgSysMemUsage` (percent) on the existing `fortigate` module. `fortinet_health` does not repeat that scalar, because Prometheus drops a scrape that emits the same sample twice | `fgHwSensorEntAlarmStatus` where the name matches fan | same table, name matches PSU / power | `fgHwSensorEntValueNumber` where the name matches temp. The MIB value is a string; the generator extracts the number | snmp-exporter `fortinet_health` added to the existing FortiGate module list |
| Palo Alto PAN-OS | `if_mib` | `HOST-RESOURCES-MIB` `hrStorage*` where the description matches physical or dynamic memory | `ENTITY-SENSOR-MIB` `entPhySensorOperStatus` for rpm sensors. `panEntryFanTrayPowerUsed` is watts, not a failed bit | `entPhySensorOperStatus` when a sensor is a power supply. `panEntryPowerSupplyPowerCapacity` is watts | `entPhySensorValue` for celsius, scale units | snmp-exporter `if_mib`, `paloalto_health` |

Module choice is `config/discovery/module-map.yml`. A device custom field `snmp_module` still wins. `__meta_netbox_snmp_auth` is unchanged (`ntt_snmpv3_auth`, `ie_snmp_v2`, `ie_wlc_v2`). `wireless-controller/ios-xe` is the 9800 list. `wireless-controller/aireos` is the AireOS list. Access-point roles publish module `skip` and the SNMP jobs drop them. `if_mib`, `cisco_cdp`, `lldp`, and the existing `cisco_wlc_universal` module stay in `snmp/out/snmp.yml`. The default WLC job no longer requests `cisco_wlc_universal`, because that module walks per-AP tables.

Generator input for the new modules is `snmp/generator-health.yml` (also appended to `snmp/generator.yml`). MIBs are under `snmp/mibs/`. A full `snmp-generator` container run rewrites `snmp/out/snmp.yml` from `generator.yml` only. Merge new modules into the live file instead of replacing `if_mib`, `cisco_cdp`, `lldp`, and `cisco_wlc_universal`.

## Access points at this scale

About 8,500 APs. One Catalyst 9800 holds about 5,000 of them. The other 3,500 sit on the remaining 11 controllers, a mix of AireOS and IOS-XE.

Telegraf service `telegraf-wlc` renders one SNMP input per controller per table from the same NetBox HTTP SD Prometheus uses (`role=wireless-controller`). Communities and SNMPv3 passwords are the existing `SNMP_V2_COMMUNITY` / `SNMP_V3_*` variables. The rendered file is `/tmp` inside the container and is not committed.

Tables, and only these columns:

| Platform | Table | Columns | Interval | Offset | Timeout |
|---|---|---|---|---|---|
| 9800 / IOS-XE | status | `cLApName`, `cLApAdminStatus`, `cLApUpTime` | 5m | 0s | 180s |
| 9800 / IOS-XE | clients | `cLApActiveClientCount` | 5m | 180s | 180s |
| 9800 / IOS-XE | radio | `cLApDot11IfType` | 10m | 360s | 240s |
| 9800 / IOS-XE | channel | `bsnAPIfPhyChannelNumber`, `bsnAPIfLoadChannelUtilization` | 10m | 480s | 240s |
| AireOS | status | `bsnAPName`, `bsnAPOperationStatus` | 5m | 0s | 120s |
| AireOS | clients | `bsnAPIfLoadNumOfClients` | 5m | 120s | 120s |
| AireOS | radio | `bsnAPIfPhyChannelNumber` | 10m | 240s | 180s |
| AireOS | channel | `bsnAPIfLoadChannelUtilization` | 10m | 300s | 180s |

`cLApIfLoadChannelUtilization` is notify-only, so channel utilization on a 9800 is read from the AIRESPACE load table, which IOS-XE still serves. AireOS `bsnAPTable` has no uptime column. Uptime for those APs stays blank.

Every input uses `max_repetitions = 10` and `retries = 1`. A larger repetition count builds bigger UDP responses and costs more CPU on the controller. Prometheus scrapes Telegraf's `:9273` every 60s with a 20s timeout. That scrape is not the SNMP walk. Series stay for 20 minutes so a 10 minute radio collection does not expire them.

`IE_WLC_SHARD_COUNT` and `IE_WLC_SHARD_INDEX` split controllers across processes. Put the 5,000-AP 9800 on its own Telegraf. `IE_WLC_TABLE=status|clients|radio|channel` runs a single table, which is the way to split that 9800 further if one process cannot keep the walks from overlapping.

The device page lists APs 50 at a time (`GET /api/v1/access-points`) with a name filter. It does not render 5,000 rows. Grafana dashboard **Device Health** shows aggregates and the top 20 radios, not the full set.

### Series count for one 5,000-AP 9800

Measured as Influx points from `telegraf --test` against snmpsim. Prometheus splits each field into its own series.

| Walk | Influx points | Prometheus series |
|---|---|---|
| status (admin + uptime) | 5,000 | 10,000 |
| clients | 5,000 | 5,000 |
| radio type, 2 radios | 10,000 | 10,000 |
| channel + utilization, 2 radios | 10,000 | 20,000 |
| **Total** | **30,000** | **about 45,000** |

Tags on every series: `wlc`, `site`, `platform`, `ap_name`, `index` (MAC as dotted decimals), `agent_host`. Recording rules do not copy these series. They only add `ie:wlc_aps_joined`, `ie:wlc_clients`, `ie:site_aps_joined`, and `ie:site_clients`.

The other 3,500 APs, at the same two radios, are on the order of 30,000 more series. The fleet stays under about 80,000 AP series. That is comfortable for Prometheus. It is not comfortable as a Grafana table.

### Load test (Docker, snmpsim, not a real 9800)

`prom/snmp-exporter:v0.30.1`, `telegraf:1.38.3`, and a local `ie-snmpsim` image (snmpsim 1.1.7). A user-defined Docker bridge did not deliver UDP replies to snmp_exporter, so the proof used `--network host` with the simulator on `127.0.0.1:1161` (small multi-vendor fixture) and `:1162` (5,000 APs). Fixtures are built by `snmp/test/run_docker_health.py`. OIDs in an `.snmprec` must be sorted or snmpsim skips them.

snmp_exporter returned the expected samples: `ifHCInOctets` with `ifAlias="critical-path"`, `ciscoEnvMonFanState` / temperature 42°C / supply state, `ciscoMemoryPoolUsed`, `cempMemPoolUsed`, `entSensorValue` 47, `cefcFanTrayOperStatus`, `fgHwSensorEntValueNumber` 55, `hrStorageUsed`, `agentCurrentCPUUtilization` 12, `bsnGlobalDot11SystemMobileStations` 120, `cLApGlobalAPConnectCount` 2 on the small fixture and 5000 on the big one. `cisco_cdp` and `lldp` still load; the fixture has no neighbours, so those scrapes are empty and successful.

Telegraf `--test` durations against snmpsim on the same host, `max_repetitions=10`, `retries=0`:

| Table | Duration | Points |
|---|---|---|
| status | 3.0s | 5,000 |
| clients | 2.1s | 5,000 |
| radio | 2.1s | 10,000 |
| channel | 4.1s | 10,000 |

snmpsim CPU after the walks was idle (about 0.04% of one core, about 43 MB). The walks were too short to sample a spike. This duration is not what a Catalyst 9800 will do. Each GETBULK of 10 rows is one round trip. Status is 3 columns × 5,000 rows / 10 ≈ 1,500 round trips. At 50 ms RTT that is about 75 seconds. At 100 ms it is about 150 seconds, which is most of the 180 second timeout and will overlap the next staggered table. Channel utilization is 2 columns × 10,000 radios / 10 ≈ 2,000 round trips.

Watch the 9800 control-plane CPU (`cpmCPUTotal5minRev` is already collected) during the first real poll. Per-AP detail and per-client RSSI on a Catalyst 9800 come from model-driven telemetry, not SNMP client walks. See `docs/wlc-9800-full.md`. `IE_WLC_LEGACY_SNMP=1` restores the small SNMP AP tables for a comparison walk. snmp-exporter still collects chassis health, joined AP count and the client total. AireOS stays on SNMP counts and inventory. `bsnMobileStation` is not walked.

`promtool check rules` accepted `health-rules.yml` (17 rules) and the existing `alert-rules.yml` (47 rules).

## What was not proven on real hardware

No Catalyst, ISR, Nexus, AireOS WLC, 9800, FortiGate, or Palo Alto was polled. The OIDs come from the vendor MIBs and from snmpsim fixtures shaped like those MIBs. In particular:

- A 2960 often reports temperature as a state and leaves the degree value at 0. The recording rule ignores a zero `ciscoEnvMonTemperatureStatusValue`. Confirm on a real 2960 whether `ciscoEnvMonTemperatureStatusValueRev1` is the one that moves.
- Some 2960s have a fixed power supply and a fan that is only a trap. The panel will say no sample, or not supported, until a row exists.
- NX-OS memory is not always `cempMemPool*`. If a Nexus only fills another pool, the ratio stays absent.
- AireOS fan and temperature are documented as unsupported polls. A box that also answers `CISCO-ENVMON-MIB` will show those rows because `cisco_env` is on the module list.
- FortiGate sensor names differ by model (`FAN 1`, `PS1 Status`, `Temperature`). The fan/PSU rules match the name. A sensor with a different spelling will not fold into `ie:device_fan_ok`.
- Palo Alto fan and PSU state depend on `ENTITY-SENSOR-MIB`. The PAN-ENTITY-EXT tables are watts and capacity, not a failed bit.
- The 2–4 second walks are snmpsim on localhost. They do not include WLC CPU, SNMP process scheduling, or WAN delay. Do not treat them as a capacity plan for the 5,000-AP 9800 until one production walk has been timed.
