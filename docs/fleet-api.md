# Fleet API

`ie-config` serves the customer UI's device, site and alert screens. Every route below is under `/api/v1`, uses the same session cookie as Settings, and returns `401` with `{ "error": { "code": "unauthorized", ... } }` when the cookie is missing.

A fresh install with zero NetBox devices and empty Prometheus and Alertmanager returns empty lists and zero counts. It does not return 404 or 500 for "nothing here yet".

NetBox is the inventory. Prometheus is health, throughput, CPU, memory and port counters. Alertmanager is the alert list. Acknowledge creates a 24 hour silence (`createdBy` is the signed-in email). Nothing else writes.

## Not verified on a live stack

Nothing in this change was run against a running NetBox, Prometheus or Alertmanager. The unit tests use mocked HTTP. `docker compose config` was checked with dummy environment values only. Metric names match `config/prometheus`, `snmp/generator.yml` and the snmp_exporter output in this repo (`ifHCInOctets`, `ifHCOutOctets`, `ifOperStatus` / `ifOperStatus_info`, `sysUpTime` in hundredths of a second, `cpmCPUTotal5minRev`, `fgSysCpuUsage`, `ciscoMemoryPoolUsed` / `Free`, `fgSysMemUsage`, `probe_success`, `up`). Labels `hostname`, `site`, `device_role` and `instance` match the NetBox http_sd relabel in `config/prometheus/prometheus.yml`.

`NETBOX_URL` stays `http://netbox:8080` (the same URL discovery already uses). If that URL is `https` and `IE_CA_FILE` exists (compose mounts `./certs/ca.crt` at `/etc/ie-certs/ca.crt`), the client trusts that CA. `https://caddy:8443` is the proxy Prometheus uses; ie-config does not need it for the plain NetBox port.

## When an upstream is down

| Upstream | List, summary, sites | Device metric arrays | Alert list | `GET /health` |
|---|---|---|---|---|
| NetBox down, or token missing | `502` `upstream_unavailable` (an empty list would look like a real empty fleet) | same, because inventory is required | same | `200`, that upstream `status` is `down` or `unconfigured` |
| Prometheus down | `200` with `degraded: ["prometheus"]`. Devices with no telemetry are `unreachable` | `502` (the UI requires a bare array) | not used | `200`, prometheus `down` |
| Alertmanager down | summary adds `alertmanager` to `degraded` | not used | `502` (an empty list would look like no alerts) | `200`, alertmanager `down` |

`GET /api/v1/devices/{form}` where `{form}` is a faceplate key (`switch-stack`, `access-switch-24`, `firewall`, …) and no device has that form returns `200` and an empty detail shell, so the default device page is not an error on a fresh install. An unknown numeric id is `404`.

## Endpoints

Auth for the GET routes is any signed-in role. Acknowledge is forbidden for Read-only (`403`). Discovery scan routes stay on the Settings reader rule (Administrator and Engineer).

| Method and path | Source | Notes |
|---|---|---|
| `GET /health` | NetBox `GET /api/dcim/devices/?limit=1`, Prometheus and Alertmanager `/-/healthy` | `{ ok, status: ok\|degraded, upstreams.{netbox,prometheus,alertmanager} }` each `{ ok, status }` |
| `GET /summary` | NetBox devices + batched PromQL + Alertmanager | `{ total, healthy, warning, critical, unreachable, alerts, isExampleData: false }` plus `degraded` when needed |
| `GET /devices?page=&page_size=&q=&health=&role=&sort=` | NetBox devices, one PromQL batch cached for `FLEET_CACHE_SECONDS` (default 8) | `{ rows, total, isExampleData: false, roles }`. `page_size` is clamped to 1..200. `q` matches hostname, IP or site. `role` matches the display name or the NetBox slug. Sort keys are the row fields; health sorts by severity, uptime and last poll by number |
| `GET /devices/{id}` | NetBox device (id or hostname) or a form-factor key such as `switch-stack` | Detail object: faceplate, checks, hardware, issues. Port id is the ifIndex so names that contain `/` do not break the path. No CPU/memory value is invented when SNMP did not return one |
| `GET /devices/{id}/metrics/throughput?range=` | `rate(ifHCInOctets)` and `ifHCOutOctets`, errors from `ifInErrors` | Bare array of `{ t, label, inBps, outBps, errors, util }`. `inBps` / `outBps` are Mbps. `range` is `1h`, `6h`, `24h`, `7d`, or `custom` with `custom_min` |
| `GET /devices/{id}/metrics/resources?range=` | Cisco or FortiGate CPU, memory percent, temperature | Bare array of points with `cpu`, `mem`, `temp` |
| `GET /devices/{id}/ports/top?metric=util` | 5 minute rate (15 minute when the window is 24h or more) against `ifHighSpeed` | `[{ name, util }]`, at most 8. `metric` must be `util` |
| `GET /devices/{id}/ports/{portId}/metrics?range=` | same counters filtered by `ifIndex` or `ifName` | Same series shape as throughput. `{portId}` may use `~` where the name had `/` |
| `GET /devices/ports/{portId}/metrics?range=` | same, without a device selector | Kept because the previous live client omitted the device id |
| `GET /sites?page=&q=&health=&region=` | NetBox sites, device health, open alerts | `{ rows, total, isExampleData: false, regions }` |
| `GET /sites/{id}/devices` | devices whose site id, slug or name matches. `site-0001` is accepted as id `1` | Bare array of device rows. Unknown site is `[]` |
| `GET /alerts?status=&severity=&site=` | Alertmanager `GET /api/v2/alerts` and `/api/v2/silences` | Bare array. `silencedBy` means `acknowledged`, and `acknowledgedBy` comes from the silence `createdBy`. The UI also filters in the browser |
| `POST /alerts/acknowledge` `{ ids }` | `POST /api/v2/silences` | `{ ids, ok }`. Matchers are the alert's labels. Already silenced ids are returned without a second silence |
| `POST /alerts/webhook` | none stored | `{ ok, received }`. Alertmanager remains the source of truth, so this does not insert alerts. If `ALERT_WEBHOOK_TOKEN` or `ALERT_WEBHOOK_TOKEN_FILE` is set, the request must send `Authorization: Bearer`. The sample in `ui/src/lib/mock/catalog.ts` points at `http://ie-config-ntt:8080/api/v1/alerts/webhook`; the settings Webhook tab is not wired to this route |
| `GET /discovery/unapproved` | ie-config `discovery_candidates` | UI shape: `id` string, `hostname`, `sysName`, `suggested.role`, `suggested.site`. Empty array when nothing is pending |
| `POST /discovery/scan` `{ target, value }` | appends a CIDR to `scan-once.txt` and touches `scan-now` | `{ id, target, value, status: "queued", startedAt, message }`. `ip` is queued as a `/32`. The Netdisco scheduler walks `scan-once.txt` and deletes it. Status stays `queued`; ie-config cannot see when Netdisco finishes |
| `GET /discovery/scans` | `discovery_scans` table | Newest 20. Empty array on a fresh install |
| `POST /discovery/{id}/approve` | existing NetBox create | `{ ok, id, device }`. `id` is a string |
| `POST /discovery/{id}/reject` | existing status update | `{ ok, id }` |
| `GET /settings/overview` | Docker proxy inspect + reload state | Adds `generatedAt`, `lastReloadAt` and `lastError` next to the previous `lastReload` field |
| `GET /settings/apps/snmp-generator/mibs` | MIB directory | Each file includes `uploadedAt` (mtime) |

Device and site rows are walked from NetBox in pages of 1000 (at most 40 pages). Fleet PromQL is a fixed set of `max by` / `count by` queries, not one query per device. Results are cached for a few seconds.

Health rules: ICMP `probe_success == 0`, no probe and no SNMP, SNMP down without a successful probe, or a last counter older than 30 minutes means `unreachable` (ports up forced to 0, uptime `—`). Admin-up operationally down ports are `critical`. Interface error rates or SNMP down while the probe is up are `warning`. Otherwise `healthy`. A site's health is the worst member; a site with no devices is `healthy`.

## UI calls that do not hit a new route

Login, logout, `GET /auth/me`, settings file CRUD, MIB upload/delete, and discovery approve/reject were already implemented. `GET /setup/state` is the setup service, not ie-config. The command palette, top bar alert count and sidebar "Not in NetBox" count call `summary`, `devices`, `sites`, `discovery/unapproved` and `/setup/state`.

Screens that still do not call an API, and why, are listed in the pull request under "Not done".
