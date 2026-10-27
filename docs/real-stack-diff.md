# Real stack compared with this bundle

Source: the sanitized tree in `reference/ntt-real-stack/`. Nothing in that tree is a secret, a customer address, or a private key. Decisions below are for the owner.

## Kept from the real stack

- Prometheus `v3.11.3`, Caddy `2.11.2`, SNMP exporter `v0.30.1` (already the pins here).
- Alertmanager pin moved to `v0.32.0` (this bundle had `v0.34.1`).
- Blackbox pin moved to `v0.28.0` (this bundle had `v0.29.1`).
- Telegraf pin moved to `1.38.3` (this bundle had `1.40.2`).
- Postgres pin `postgres:17.9`. The data volume stays on `/var/lib/postgresql` (the parent of the PG17 data directory). It was not switched to `/var/lib/postgresql/data`.
- Redis image default `redis:8.6.2`. This tag was **not** started here.
- `snmp/out/snmp.yml` is the generated file from the real exporter (auths `ntt_snmpv3_auth`, `ie_snmp_v2`, `ie_wlc_v2`, all via `${SNMP_*}`). `SNMP_V3_USERNAME` is set from `SNMP_V3_USER` because the file uses that name and this compose previously only had `SNMP_V3_USER`.
- Prometheus jobs follow the real http_sd pattern: active devices, primary IP, relabel of `__meta_netbox_name`, `__meta_netbox_site_name`, `__meta_netbox_role`, `__meta_netbox_device_type`, `__meta_netbox_region`, `__meta_netbox_primary_ip4`, `__meta_netbox_tenant`, `__meta_netbox_site_group`. Module lists match the real jobs. `refresh_interval` is 5m so a new device shows up inside 5–10 minutes.
- Blackbox ICMP modules match the real timeouts and payload. TCP and HTTP modules from this bundle were kept.
- Alert rules from the real file were copied. Collector rules (`DeviceUnreachable`, `SnmpScrapeFailing`, `CollectorDown`, `HttpSdRefreshFailing`) were appended so the Alertmanager inhibit rules still match.
- Host ssh, sysctl, and Docker daemon files were copied to `config/host/` as **read-only** Settings files. ie-config does not apply them to the OS.
- Grafana Prometheus datasource `timeInterval` is 15s, and the two Postgres datasource entries are present as `${TELEGRAF_PG_PASSWORD}` / `${AP_DATA_PASSWORD}` placeholders. Grafana does not expand those itself.

## Intentionally different

| Topic | Real stack | This bundle |
|---|---|---|
| NetBox image | `hishaam02/netbox-lists:v4.6-5.0.0` (private) | Default is a local build `insightengine/netbox-lists:local` from `netboxcommunity/netbox:v4.6.3` plus `netbox/netbox_lists`. Set `NETBOX_IMAGE` to the private tag to pull it instead. `install.sh` will not rebuild over that tag. |
| Prometheus → NetBox | Direct `http://netbox-ntt:8080/api/plugins/lists/prometheus-devices/` and a token file on the Prometheus container | Same plugin URL, through Caddy `https://caddy:8443`, token at `/run/secrets/netbox_token`, CA file for that TLS hop. |
| Exporters | One `blackbox-exporter-ntt` and one `snmp-exporter-ntt` | `scrape-lb` in front of two (or more, profile `scale`) exporters. |
| Alert delivery | Webhook to an external insights-engine host with a bearer token file | Internal `alert-relay` and `destinations.json`. The external webhook was not copied. |
| Grafana image | `grafana/grafana:13.1.0-25027462778` | Public `grafana/grafana:13.0.11`. |
| Activepieces | `0.88.1` | `0.92.3-hotfix.1` (kept). |
| Postgres layout | One shared Postgres | Per-app Postgres, including Netdisco and the `ie_config` database. |
| Telegraf | One combined config | Split api / host / syslog files. |
| Caddy | Published exporter ports and a basic-auth hash | This bundle's setup/UI routing, plus `/api/v1`. The hash was not copied. |
| Access-switch SNMP module | Job said `cisco_pr` | `snmp.yml` has `cisco_pro`. Jobs and the module map use `cisco_pro`. |
| Palo Alto | No `paloalto_*` module in the live `snmp.yml` | `generator.yml` has a starter `paloalto_system` walk. Until it is generated, the module map uses `if_mib` for Palo Alto. |
| Syslog | Promtail is not what this engine runs | App id `promtail-or-syslog` is the Telegraf syslog collector, so the UI contract id still exists. |

## Catch-all jobs

Dedicated jobs exist for the roles above. `icmp-other` and `snmp-other` take every other **active** device that has a primary IP, and drop the roles that already have a job, so a device is not scraped twice. `__meta_netbox_snmp_module` and `__meta_netbox_snmp_auth` override the job default when the plugin sets them.

## Token used for Prometheus

`install.sh` writes the NetBox **superuser** API token into `secrets/prometheus/netbox.token` and `secrets/oxidized/netbox.token` so a device added after first-run is monitored without a manual step. That token is privileged. Replace it with a read-only token via `scripts/set-secret.sh prometheus/netbox.token` when you can.

## Not copied

Customer site names, hostnames, and the original `ie_switches_shard_1.json` rows. The reference file is one placeholder target. The bcrypt hash from the real Caddyfile. Any `.env` that contained real passwords (the reference `.env.example` still has `CHANGE_ME` style placeholders and the documentation address).
