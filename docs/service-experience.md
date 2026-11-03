# Service experience

Four checks sit next to device health. None of them push configuration onto a router or a controller. The device page and the API only show text to paste.

| Check | Where it is configured | How it is collected |
|---|---|---|
| WLC AP and client experience | Catalyst 9800 telemetry subscription, or AireOS SNMP | Telegraf |
| SD-WAN tunnel loss, latency, jitter | cEdge telemetry subscription | Telegraf MDT. SNMP is session up/down only |
| IP SLA to the site VBS server | IOS `ip sla` paste, plus site custom fields | snmp-exporter `cisco_rttmon` |
| Third parties, banks, and the VBS ping | NetBox services and `vbs_server_ip` | blackbox-exporter |

The UI page is **Service Experience**. Empty groups say **not configured**. Grafana dashboard **Service Experience** is provisioned from `config/grafana/provisioning/dashboards/json/service-experience.json`. Alerts and recording rules are `config/prometheus/experience-rules.yml`.

Per-client wireless samples are not stored in Prometheus unless `IE_WLC_STORE_CLIENTS=1`. One Catalyst 9800 holds about 5,000 APs. Telegraf keeps the client MAC in memory and exports per AP and per radio: average and minimum RSSI, average and minimum SNR, and the client count. Recording rules then add per-site averages. Turning on per-client series is optional and will be a large number of series (thousands of clients times RSSI and SNR). Leave it off.

## NetBox fields

`netbox-experience-fields` runs once at boot and is safe to run again. It creates:

| Object | Name | Meaning |
|---|---|---|
| Site | `vbs_server_ip` | IP or hostname of that site's VBS server |
| Site | `vbs_server_port` | TCP port, default **9999** |
| Service | `probe` | `icmp` or `tcp` |
| Service | `target` | IP or hostname when the service has no parent device address |
| Tag | `third-party` | Blackbox target that is a third party |
| Tag | `bank` | Blackbox target that is a bank |

The task does not create any service. Add a bank or a third party yourself. Do not put a real customer address into git.

A site with no `vbs_server_ip` is not pinged and its routers show **not configured** on the IP SLA button.

## Catalyst 9800 telemetry

SNMP on a 9800 does not give useful per-client RSSI/SNR or per-radio noise and interference, and the per-AP walks in the health work are the wrong tool at 5,000 APs. Those Telegraf SNMP tables are no longer rendered for IOS-XE controllers. snmp-exporter still polls chassis health and `cLApGlobalAPConnectCount` (`cisco_wlc_iosxe`). `IE_WLC_LEGACY_SNMP=1` restores the old AP tables for a comparison; leave it unset in production.

`telegraf-wlc` listens for gRPC dial-out on port **57500** (`inputs.cisco_telemetry_mdt`, `service_address = ":${IE_MDT_PORT}"`). `IE_MDT_PORT` and `PORT_MDT` default to 57500 and can be changed together. Set `IE_MDT_RECEIVER` to an address the controller can route to. The generated line is `receiver ip address <server> 57500`.

Open **TCP 57500** on the collector for that dial-out. **57400** is UI HTTPS when 443 is already taken; MDT does not use it. Host port 57500 used to publish telegraf-host `/metrics` (`PORT_TELEGRAF` → container 9273). That publish is now **57501**, so it does not bind the MDT port. Prometheus still scrapes `telegraf-host:9273` on the docker network. gNMI dial-in does not use 57500: Telegraf dials the controller on port 9339.

On the device page, **Telemetry subscription** copies the IOS-XE CLI. The same text is `GET /api/v1/devices/{id}/telemetry-config`. It is not applied for you.

Subscriptions, 60 second periodic (`update-policy periodic 6000`, the unit is centiseconds) plus on-change where the data is an event:

| Path | Policy | What it is |
|---|---|---|
| `/wireless-client-oper:client-oper-data/traffic-stats` | periodic | `most-recent-rssi`, `most-recent-snr` |
| `/wireless-client-oper:client-oper-data/common-oper-data` | periodic | AP name and radio slot, joined to the RSSI row inside Telegraf and then dropped |
| `/wireless-rrm-oper:rrm-oper-data/rrm-measurement` | periodic | channel utilization (`cca-util-percentage`), noise, interference |
| `/wireless-access-point-oper:access-point-oper-data/capwap-data` | on-change and periodic | AP state, reboot reason (CAPWAP join/leave) |
| `/wireless-access-point-oper:access-point-oper-data/radio-oper-data` | on-change and periodic | channel, tx power |
| `/wireless-access-point-oper:access-point-oper-data/ssid-counters` | periodic | clients per WLAN, summed to the radio |

YANG modules: `Cisco-IOS-XE-wireless-client-oper`, `Cisco-IOS-XE-wireless-rrm-oper`, `Cisco-IOS-XE-wireless-access-point-oper`.

gNMI dial-in is the other transport. Set `IE_WLC_MDT_TRANSPORT=gnmi`, `IE_GNMI_USER` and `IE_GNMI_PASSWORD`. Telegraf then dials each 9800 on port 9339. Do not also point the controller at the dial-out port for the same paths. The password is rendered into the container's temporary config and is not committed.

Only shard 0 opens port 57500. Extra AireOS shards set `IE_WLC_SHARD_INDEX` and leave the listener to the 9800's Telegraf (`IE_WLC_MDT=0` on the extras, `IE_WLC_MDT=1` on the collector).

## AireOS

AireOS has no MDT. Telegraf keeps the SNMP tables from the health work and adds client RSSI and SNR:

| Table | Columns |
|---|---|
| `bsnAPIfLoadParametersTable` | `bsnAPIfLoadChannelUtilization`, and the existing client count column |
| `bsnMobileStationTable` | AP MAC `1.3.6.1.4.1.14179.2.1.4.1.4`, radio slot `…​.5` |
| `bsnMobileStationStatsTable` | RSSI `1.3.6.1.4.1.14179.2.1.6.1.1`, SNR `…​.26` |

The station walk shares the client MAC index, so one Telegraf table carries AP, radio, RSSI and SNR. The processor drops the client before Prometheus, same as MDT. AireOS does not report RRM noise and interference in that load table. The telemetry button on an AireOS controller says it is not configured.

## SD-WAN cEdge

Role `cedge`, `sdwan-edge` or `wan-edge`, or platform `ios-xe-sdwan`. The FortiGate role `sdwan` is not a cEdge and is unchanged.

The telemetry button generates:

| Path | Policy |
|---|---|
| `/sdwan-oper:sdwan-oper-data/bfd/sessions` | periodic and on-change |
| `/sdwan-oper:sdwan-oper-data/app-route/statistics` | periodic |

Labels are local color, remote color and the peer address. Loss values above 1 are treated as a percent and divided by 100, which matches `show sdwan app-route stats`.

`Cisco-IOS-XE-sdwan-oper` is the on-box model. It is not in the public YangModels tree, so the leaf names are matched loosely (`loss`, `latency`, `jitter`, `local-color`, `remote-color`, `state`). Confirm the encoding path on the first router with `show telemetry ietf subscription`.

SNMP `cisco_sdwan_bfd` walks `ciscoBfdSessState` (`1.3.6.1.4.1.9.10.137.1.2.1.6`, up = 4). That MIB has no loss, latency or jitter. The alert `SdwanBfdSessionDown` is only the session. The quality alerts use the MDT series.

## IP SLA to the VBS server

1. Set `vbs_server_ip` and, if it is not 9999, `vbs_server_port` on the site.
2. Open the Cisco IOS or IOS-XE router at that site. **IP SLA config** copies the CLI. `GET /api/v1/devices/{id}/ip-sla-config` returns the same text. `pushed` is false.
3. Paste it. The operation ids are stable for that router name.

The text is `tcp-connect` to the VBS IP and port, sourced from the router's management IP, every 60 seconds. IOS and IOS-XE also get `udp-jitter` (the VBS server must answer UDP on that port) and `icmp-jitter` (no responder). Classic IOS needs 12.4(4)T or later for `icmp-jitter`. Delete a block the image rejects.

snmp-exporter module `cisco_rttmon` is on the IOS and IOS-XE module lists:

| Object | OID | Use |
|---|---|---|
| `rttMonLatestRttOperCompletionTime` | `1.3.6.1.4.1.9.9.42.1.2.10.1.1` | latency, milliseconds |
| `rttMonLatestRttOperSense` | `1.3.6.1.4.1.9.9.42.1.2.10.1.2` | 1 is ok |
| `rttMonLatestJitterOperNumOfRTT` | `1.3.6.1.4.1.9.9.42.1.5.2.1.1` | successful samples |
| `rttMonLatestJitterOperPacketLossSD` | `…​.26` | loss source to destination |
| `rttMonLatestJitterOperPacketLossDS` | `…​.27` | loss destination to source |
| `rttMonLatestJitterOperAvgJitter` | `…​.46` | jitter, milliseconds |
| `rttMonJitterStatsPacketLossSD` | `1.3.6.1.4.1.9.9.42.1.3.5.1.34` | hourly stats table |
| `rttMonJitterStatsAvgJitter` | `…​.62` | hourly average jitter |

The tag `rttMonCtrlAdminTag` is the lookup label. Recording rules: `ie:ipsla_rtt_ms`, `ie:ipsla_loss_ratio`, `ie:ipsla_jitter_ms`, `ie:ipsla_ok`.

Blackbox also pings `vbs_server_ip`, labelled by site (`blackbox-vbs-icmp`). That job's HTTP SD refresh is 5 minutes.

## Third parties and banks

1. Create a NetBox service. Do not commit the address.
2. Tag it `third-party` or `bank`.
3. Set `probe` to `icmp` or `tcp`.
4. Set `target` to the IP or hostname, or put the service on a device that has a primary IPv4.
5. For `tcp`, set the service port.

`GET /api/plugins/lists/prometheus-services/?tag=third-party&probe=icmp` (and the bank and tcp variants) is HTTP SD for blackbox. `refresh_interval` is **5m**, so a new target is scraped within 5 minutes. Jobs:

- `blackbox-third-party-icmp`
- `blackbox-third-party-tcp` (`tcp_connect`, target `host:port`)
- `blackbox-bank-icmp`
- `blackbox-bank-tcp`
- `blackbox-vbs-icmp`

Dashboard columns are up (`ie:probe_up`) and latency (`ie:probe_latency_seconds`). Alerts: `ThirdPartyProbeDown` (5 minutes), `VbsPingDown` (5 minutes).

## Alerts

| Alert | For | Condition |
|---|---|---|
| `WifiRssiLow` | 10m | per-radio average RSSI below -75 dBm |
| `WifiSnrLow` | 10m | per-radio average SNR below 15 dB |
| `WifiChannelBusy` | 10m | channel utilization above 70% |
| `WlcApDown` | 5m | MDT AP oper state not up |
| `SdwanTunnelLoss` | 10m | loss above 2% |
| `SdwanTunnelLatency` | 10m | latency above 150 ms |
| `SdwanTunnelJitter` | 10m | jitter above 30 ms |
| `SdwanTunnelDown` | 5m | MDT BFD not up |
| `SdwanBfdSessionDown` | 5m | SNMP session state not up |
| `IpSlaHighLatency` | 10m | RTT above 200 ms |
| `IpSlaLoss` | 10m | jitter loss above 5% |
| `IpSlaDown` | 5m | latest sense is not ok |
| `ThirdPartyProbeDown` | 5m | bank or third-party probe down |
| `VbsPingDown` | 5m | site VBS ping down |

## What a lab can prove, and what it cannot

Docker tests use a simulated gRPC dial-out sender, snmpsim for `CISCO-RTTMON-MIB` and `CISCO-IETF-BFD-MIB`, blackbox against local targets, and a mock NetBox HTTP SD. They do not prove a Catalyst 9800, an AireOS controller, or a cEdge.

On the first real 9800, confirm the encoding paths and that `most-recent-rssi` is on `traffic-stats` for that IOS-XE release. On the first cEdge, confirm `Cisco-IOS-XE-sdwan-oper` is present and that app-route loss is a percent. `icmp-jitter` and `udp-jitter` depend on the image and on a UDP responder. The BFD SNMP walk does not contain loss, latency or jitter.
