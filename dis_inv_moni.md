# Discover, inventory and monitor a device (dis_inv_moni)

Step by step: get a device into NetBox (by discovery or by hand) and have InsightEngine monitor it.
Server path: `/opt/arg/insightengine`. Run every command there. Placeholders are in `<angle brackets>`; never paste real secrets into tickets or chat.

| App | URL |
|---|---|
| InsightEngine UI | `https://<server>:57400` (login `/login-screen`) |
| NetBox | `http://<server>:8092` (`PORT_NETBOX`) |
| Grafana | `http://<server>:3000` |
| Prometheus | `http://<server>:9090` |
| Alertmanager | `http://<server>:8086` |
| Netdisco | `http://<server>:15000` |
| Oxidized | `http://<server>:18888` |

Note: `.env.example` defaults are `PORT_NETDISCO=5000` and `PORT_OXIDIZED=8888`. 15000/18888 are this server's values in `.env`.
Logins for every app are in **Settings → Vault** (admins only).

---

## 0. Device prerequisites

The device must allow, from the InsightEngine server IP (`<server-ip>`):

- **UDP 161** (SNMP polls by snmp-exporter and Netdisco; TCP is not used)
- **ICMP echo** (blackbox `icmp` module; also used by the Netdisco pre-sweep)
- **TCP 22** (SSH for Oxidized backups and the Device CLI page)

SNMPv3 `authPriv` is preferred. v2c works too.

Cisco IOS-XE:
```
ip access-list standard IE-SNMP
 permit host <server-ip>
snmp-server view IE-VIEW iso included
snmp-server group <v3-group> v3 priv read IE-VIEW access IE-SNMP
snmp-server user <v3-user> <v3-group> v3 auth sha <auth-pass> priv aes 128 <priv-pass>
! v2c alternative:
snmp-server community <community> RO IE-SNMP
```

FortiGate:
```
config system interface
 edit "<mgmt-port>"
  append allowaccess ping snmp ssh
 next
end
config system snmp user
 edit "<v3-user>"
  set notify-hosts <server-ip>
  set security-level auth-priv
  set auth-proto sha
  set auth-pwd <auth-pass>
  set priv-proto aes
  set priv-pwd <priv-pass>
 next
end
```

PAN-OS:
```
set deviceconfig system service disable-snmp no
set deviceconfig system permitted-ip <server-ip>
set deviceconfig system snmp-setting access-setting version v3 views IE-VIEW view all oid 1.3.6.1 option include
set deviceconfig system snmp-setting access-setting version v3 users <v3-user> view IE-VIEW authpwd <auth-pass> privpwd <priv-pass>
```
(Check the management profile allows ping, SNMP and SSH. The PAN-OS SNMP auth/priv algorithm is set per release; match it in `monitoring_snmp`.)

---

## 1. NetBox base objects (NetBox :8092)

| What | Where | Notes |
|---|---|---|
| Regions | Organization → Regions | **Preloaded.** 644 regions: Africa → sub-region → country → province (e.g. `za-gauteng`). Loaded by the `netbox-regions` one-shot from `netbox/regions/regions.yaml`. Don't create duplicates. |
| Tenant + client region | — | Created by `scripts/seed-netbox.sh` from `CLIENT_SLUG` (separate root region). |
| Site | Organization → Sites → Add | Set **Region** to the province (e.g. Gauteng `za-gauteng`). Status Active. |
| Device roles | Devices → Device Roles | Seeded: `access-switch`, `core-switch`, `distribution-switch`, `sdwan`, `hub`, `core-firewall`, `wireless-controller`. These slugs drive Prometheus jobs and SNMP modules. Other roles still get monitored by the catch-all jobs. |
| Platforms | Devices → Platforms | Not seeded by the repo. Create as needed; `fortigate` and `pan-os` slugs have SNMP mappings in `config/discovery/module-map.yml`. Platform also selects the Device CLI command allowlist. |
| Manufacturers + device types | Devices → Device Types | **Preloaded** for Cisco, Fortinet and Palo Alto (`netbox-device-types` one-shot, with interface/console/power templates). See `docs/device-types.md`. |
| Tag `ie-scan` | Customization → Tags | Seeded. Used to pick prefixes for discovery. |

---

## 2. Credentials

### SNMP: config context `monitoring_snmp`
NetBox → Provisioning → Config Contexts → Add. Scope it (region, site, role, platform, tenant…) and set a **weight** (higher wins). Data:

SNMPv3:
```json
{"monitoring_snmp":{"version":"3","port":161,"security_name":"<v3-user>","security_level":"authPriv","auth_protocol":"SHA","auth_passphrase":"<auth-pass>","priv_protocol":"AES","priv_passphrase":"<priv-pass>"}}
```
SNMPv2c:
```json
{"monitoring_snmp":{"version":"2c","port":161,"community":"<community>"}}
```
- `security_level`: `noAuthNoPriv`, `authNoPriv` or `authPriv`; optional `context_name`.
- NetBox deep-merges contexts: give every `monitoring_snmp` context the same keys.
- No context on a device → `.env` fallback (`SNMP_V2_COMMUNITY`, `SNMP_V3_USER`, `SNMP_V3_AUTH_PASSWORD`, `SNMP_V3_PRIV_PASSWORD`; auth names `ntt_snmpv3_auth`, `ie_snmp_v2`).
- ie-config syncs every **5 minutes** and right after a save in Settings → SNMP. It writes `data/snmp/auth-by-ip.yml`, `data/snmp/snmp.runtime.yml`, reloads the snmp-exporters and adds Netdisco `device_auth` entries.

**Alternative (secrets off NetBox):** InsightEngine UI → Settings → **SNMP**, File mode. The context then holds only `{"monitoring_snmp":{"profile":"<name>"}}`; secrets stay in `data/snmp/profiles.json` (0600). The SNMP tab has a test-device action.

### SSH
- **Oxidized** (one login for all devices): secret files `secrets/oxidized/device_username` and `secrets/oxidized/device_password`:
  ```
  sudo ./scripts/set-secret.sh oxidized/device_username
  sudo ./scripts/set-secret.sh oxidized/device_password
  sudo docker compose up -d --force-recreate oxidized
  ```
- **Device CLI page** (per device): Administration → Device CLI → pick the device → **Save credentials**. Stored in `secrets/device-cli/<id>.json` (0600) via `PUT /api/v1/devices/{id}/cli/credentials`. Read-only allowlisted commands only.

---

## 3. Discovery (Netdisco)

1. NetBox → IPAM → Prefixes → Add: prefix (e.g. `10.22.14.0/24`), status **Active**, **Site** set, tag **`ie-scan`**. (Or set `scan_all_active_prefixes: true` in `config/discovery/sync.yml`. The docs say "Settings → Netdisco", but the current UI Settings page has no Netdisco tab; edit the file or use the settings API, `docs/settings-api.md`.) Prefixes larger than /16 are skipped.
2. ie-config polls NetBox about every **60 s** (`prefix_poll_seconds`), rewrites the Netdisco prefix file and requests a scan immediately when the set changes. Full rescans run every `interval_hours` (default **6**).
3. The scheduler (`scripts/netdisco-scheduler.sh`) pre-sweeps with `scripts/presweep.pl` (TCP 22/23/80/443/830, UDP 161 if `SNMP_V2_COMMUNITY` is set, ping) and only discovers live hosts.
4. One-off scan: UI → Inventory → **Not in NetBox** → **Discover** form (Target: IP address or Prefix). API: `POST /api/v1/discovery/scan`.
5. Watch: Netdisco UI `:15000`; scan status rows on the Not in NetBox page (`GET /api/v1/discovery/scans`); logs `sudo docker compose logs -f netdisco-scheduler netdisco-backend ie-config`.

---

## 4. Approve (UI → Inventory → Not in NetBox, `/not-in-net-box`)

- New finds appear on the next one-minute refresh after the scan finishes (`GET /api/v1/discovery/unapproved`). Nothing goes into NetBox until you approve.
- **Approve** (single) or **Approve selected** (bulk; needs a suggested role and site). Role/site/platform lists come from `GET /api/v1/discovery/catalog`. Suggested site = site of the most specific active prefix containing the IP.
- Approve creates in NetBox: the device (manufacturer from Netdisco vendor), an interface, the IP on it, and sets `primary_ip4`. If a later step fails, the device is deleted again.
- Device type: an existing library type is reused if the model matches; `config/discovery/device-type-aliases.yml` maps Netdisco family names (e.g. `37xxstack` → Catalyst 3750) to library types. Otherwise a stub type is created (no interface templates). Add an alias to avoid stubs.
- A pending row whose IP is already in NetBox is dropped automatically.

---

## 5. Manual add in NetBox

NetBox → Devices → Add: name, **role**, **device type** (pick the preloaded one), **site**, platform, status **Active**. Then add/choose the management interface → IPAM → IP Addresses → Add `<mgmt-ip>/<len>` assigned to that interface → edit the device and set **Primary IPv4**.
Requirements for monitoring: status `active` + a primary IPv4. Optional device custom fields `snmp_module` / `snmp_auth` override the module map.

---

## 6. Monitoring

- Prometheus reads targets from NetBox http_sd (`/api/plugins/lists/prometheus-devices/?status=active&role=<role>`), `refresh_interval: 5m`. Allow **5–10 minutes** after adding a device.
- Jobs per role: `icmp-*` (blackbox `icmp`) and `snmp-*` (access/core/distribution switches, fortigate sdwan/hub/core-fw, cisco-wlc), plus `icmp-other` / `snmp-other` catch-alls.
- SNMP modules from `config/discovery/module-map.yml`: Cisco switch roles → `if_mib, cisco_environ, cisco_mem, cisco_pro`; FortiGate roles/manufacturer/platform `fortigate` → `if_mib_fortigate, fortigate, fortigate_bandwidth`; Palo Alto / platform `pan-os` → `if_mib`; `wireless-controller` → `cisco_wlc_universal`; default `if_mib`.
- Verify:
  - Prometheus `:9090` → Status → Targets: device under `icmp-…` and `snmp-…`, state UP. Query `up{instance="<mgmt-ip>"}`.
  - Grafana `:3000` dashboards.
  - UI → Device detail (and Sites, Alerts).
  - Alertmanager `:8086`.
  - Oxidized `:18888`: backs up NetBox devices matching `OXIDIZED_NETBOX_FILTER` (`status=active`), every `OXIDIZED_INTERVAL` (14400 s = 4 h).
  - UI → Administration → Device CLI: run a show command.

---

## 7. Interface backfill and regions

Both are merged on `main` (PR #21 backfill, PR #20 regions) and run automatically on boot/upgrade.

```
sudo ./scripts/backfill-netbox-components.sh --dry-run   # preview
sudo ./scripts/backfill-netbox-components.sh             # add missing ports
```
Adds only components a device's Device Type defines but the device lacks; never edits or deletes. Stub types are skipped. Disable with `NETBOX_BACKFILL_COMPONENTS=false` in `.env`.

Reload regions: `sudo docker compose build netbox-regions && sudo docker compose up -d --no-deps netbox-regions` (idempotent). See `docs/regions.md`, `docs/component-backfill.md`.

---

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| SNMP test shows `auth_not_loaded` | v3 profile saved seconds ago; sync not finished | Wait for the sync (≤5 min) and retest; `sudo docker compose logs ie-config \| grep -i snmp` |
| snmp-exporter returns 400 / target down with SNMP errors | Unknown auth or module name, or wrong credentials | Check the `auth`/`module` params on the target in Prometheus; check `monitoring_snmp`; `sudo docker compose logs snmp-exporter-1` |
| Target down (ICMP) | ACL/firewall drops ICMP or wrong primary IP | `ping <mgmt-ip>` from the server; check primary IPv4 in NetBox |
| Device not in Prometheus | Not `active`, no primary IPv4, or <5 min | Fix in NetBox; wait 5–10 min |
| Device missing from Not in NetBox | Prefix not tagged `ie-scan`/not active, prefix > /16, host didn't answer pre-sweep, SNMP creds wrong, or IP already in NetBox | Fix prefix; use **Discover** with the IP; `sudo docker compose logs netdisco-backend` |
| NetBox unhealthy, `GET /login/ 400` | Health check without allowed Host header | Ensure compose healthcheck uses `curl -fsS -H 'Host: localhost' http://127.0.0.1:8080/login/`; `sudo git checkout docker-compose.yml && sudo git pull && sudo ./scripts/upgrade.sh` |
| Caddy stuck in `Created`, all app links fail | Host port already in use (e.g. n8n on 9093) | `sudo ss -ltnp \| grep <port>`; change the `PORT_*` in `.env`; `sudo docker compose up -d` |
| `git pull` permission denied | `.git` owned by root | `sudo chown -R $USER: /opt/arg/insightengine/.git` (or `sudo git pull`) |

---

## 9. Checklist

- [ ] Device: SNMP v2c/v3, ACL for UDP 161 / ICMP / SSH from `<server-ip>`
- [ ] NetBox site with region (e.g. `za-gauteng`)
- [ ] Role, platform, device type chosen
- [ ] `monitoring_snmp` config context scoped (or Settings → SNMP File mode)
- [ ] Oxidized SSH secrets set; Device CLI credentials saved
- [ ] Prefix active + tag `ie-scan` (discovery) **or** device added by hand
- [ ] Approved in Not in NetBox; device has primary IPv4, status active
- [ ] Backfill dry-run clean
- [ ] Prometheus targets UP, Grafana shows data, Oxidized backup present, Device CLI works
