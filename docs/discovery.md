# Discovery

Discovered devices stay in ie-config until a person approves them. No service inserts a device into NetBox on its own, and `GET /api/v1/devices` only reads NetBox, so the fleet stays empty until approval. The queue is **Inventory → Not in NetBox** (`/not-in-net-box`), backed by `/api/v1/discovery/*`.

## Prefixes

ie-config polls NetBox about once a minute (`prefix_poll_seconds` in `config/discovery/sync.yml`, default 60) and rewrites `scan-prefixes.txt` on the Netdisco volume. Untagged prefixes are still ignored unless `scan_all_active_prefixes` is set. When the chosen set changes, ie-config raises `scan-now` so the scheduler does not wait for `interval_hours`.

**Scan prefixes now** syncs prefixes first, then sets `scan-now`.

Removing a prefix rewrites the file (the scheduler stops walking it) and deletes still-pending candidates whose address was inside that prefix and is not inside a remaining one. Approved and rejected rows are kept. The next queue refresh will not put those pending rows back.

After each scheduler pass the scheduler writes `scan-finished`. ie-config refreshes the queue on the same one-minute loop, after the prefix sync, so a device Netdisco just stored shows up on this cycle.

## Pre-sweep

`netdisco-do discover -d <cidr>` tries SNMP on every address. With Netdisco's default second slow pass (`snmp_try_slow_connect`, on by default) a dead address costs about a minute, so a /24 takes hours.

Netdisco's own range command is `netdisco-do pingsweep`, which pings and queues discover only for replies. It needs the `ping` binary and misses hosts that drop ICMP but answer SNMP or SSH.

The scheduler (`scripts/netdisco-scheduler.sh`) runs `scripts/presweep.pl` instead of `discover -d <cidr>`:

- TCP 22, 23, 80, 443, 830, UDP/161 (when `SNMP_V2_COMMUNITY` is set), and `ping` if it works
- parallel, short timeout (`presweep_timeout_seconds`, default 0.4)
- prefixes larger than /16 are skipped
- only live addresses are passed to `discover`, `macsuck`, and `arpnip`

If the probe cannot run and `ping` exists, the scheduler falls back to `netdisco-do pingsweep`. It does not SNMP-scan the whole prefix.

`sync.yml` also sets Netdisco's own timers, rendered into `deployment.yml`:

| Key | Default | Meaning |
|---|---|---|
| `snmp_timeout_us` | 1000000 | `snmptimeout`, microseconds (1 second) |
| `snmp_retries` | 1 | `snmpretries` |
| `snmp_try_slow_connect` | false | no second slow SNMP pass |

Edit them in Settings → Netdisco → `sync.yml`. ie-config re-renders `deployment.yml` on the next poll. Netdisco reads that file because `DANCER_ENVDIR` is `/home/netdisco/nd-site-local`. The rendered file is mode 600 and owned by uid 901 (the image user); if chown is not permitted it is mode 644 so the process can still open it.

## Approve

The approve form loads roles, sites, and platforms from `GET /api/v1/discovery/catalog` (cached for a minute). Mock mode still uses the demo lists.

The suggested site is the NetBox site on the most specific active prefix that contains the address (`site` on older NetBox, `scope_type: dcim.site` on 4.x). A region scope is not used. Bulk approve needs a suggested role and site; the prefix site is what makes a same-site selection succeed.

Display names ("Access switch", "Test Site") are slugified. The manufacturer comes from the Netdisco vendor (or the sysObjectID guess). Palo Alto is slug `palo-alto`. An existing library device type is reused when the model or part number matches one row; otherwise a stub type is created. Platform is created and set when the form or the guess has one.

NetBox requires the IP to be assigned to an interface before it can be the primary address. Approve creates the device, then the interface, then the IP on that interface, then sets `primary_ip4`. If any step after the device fails, the device is deleted so it does not appear in `/api/v1/devices`. A Netdisco family string such as `37xxStack` is matched to a library device type through `config/discovery/device-type-aliases.yml` (Settings → Netdisco). A stub type is created only when nothing in the library matches.

`GET /api/v1/discovery/scans` moves a row from `queued` to `finished` after the scheduler writes `scan-finished` later than the row was created.

Oxidized's default device filter is `status=active`, so an approved device and a device added by hand are both backed up. See `docs/upgrade.md`.

A pending row whose address is already a NetBox device primary IP, or any assigned IP address, is removed from the queue on the next refresh.
