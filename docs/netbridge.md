# NetBridge

NetBridge copies inventory from Netdisco, Cisco wireless controllers, and FortiManager into NetBox. The page is `/netbridge`. `/not-in-net-box` redirects there, on the Not in NetBox tab.

The sidebar badge is the number of open conflicts (`GET /api/v1/netbridge/open-count`).

## Safety

- Match order is serial, then hostname, then management IP. Hostnames match with and without `HOSTNAME_STRIP_SUFFIXES` (for example `.pnp.co.za`), the same helper the rest of InsightEngine uses.
- NetBridge never deletes a NetBox object.
- It never renames a device that already exists.
- It never overwrites site, role, or rack on a device that already exists. A new device can be given a site and role. A stack member that already exists is only given a virtual chassis and `vc_position`, and only when it is not already in a virtual chassis.
- Every write is a dry-run preview. Apply requires that preview id and `"confirm": true`.
- Creates and updates are sent in batches. One failure is recorded on the job and the rest continue.
- Mismatches of serial, name, management IP, or site are stored for review. Resolve and ignore do not change NetBox. An ignored fingerprint stays ignored.

## Tabs

| Tab | What it does |
|---|---|
| Dashboard | Counts for Netdisco devices, NetBox devices, devices not in NetBox, stacks still to attach, scanned APs not in NetBox, and open conflicts. Recent jobs and shortcuts. |
| Not in NetBox | The previous approval queue. Tick rows and approve or reject. Suggested role is a dropdown filled from `GET /api/dcim/device-roles/`. The choice is stored on the candidate until it is approved, and that role is what approval writes. Selected rows can take one role at once. Search is server-side when `page` is sent (`GET /api/v1/discovery/unapproved?page=&page_size=&q=`). A call with no query still returns the full list. |
| Stacks | Netdisco `device_module` rows whose class is chassis or stack, or whose name is `Switch N`, become one NetBox virtual chassis per stack. Each member is its own device with `vc_position`. |
| IP Addresses | Netdisco `device_ip` rows are offered for the matching device and interface. An address that already belongs to another device becomes a conflict. Primary IP is set only when the device has none. |
| Access Points | SNMP walk of WLCs. AireOS uses `AIRESPACE-WIRELESS-MIB` `bsnAPTable` (name `.1.3.6.1.4.1.14179.2.2.1.1.3`, model `.16`, serial `.17`, IP `.19`). Catalyst 9800 uses `CISCO-LWAPP-AP-MIB` `cLApName` (`.1.3.6.1.4.1.9.9.513.1.1.1.1.5`) and the AireOS table when the controller still serves it. CDP neighbour and port come from `CISCO-LWAPP-CDP-MIB` `clcCdpApCacheNeighName` / `clcCdpApCacheNeighInterface` (`.1.3.6.1.4.1.9.9.623.1.3.1.1.6` and `.9`). GetBulk keeps a controller with about 5000 APs to a few hundred packets. Filter buttons are the models from the last scan. Upload creates missing APs only. |
| Wireless Controllers | NetBox role `wireless-controller`, Netdisco devices whose model looks like a WLC, and optional `config/discovery/wlc-targets.yml` (`targets: [{ip, name, platform}]`). Missing controllers can be created. AP counts come from the last scan. |
| FortiManager | Read-only. One instance from the vault URL and token. Managed FortiGates are compared to NetBox. Nothing is written. |
| Sites | Sites missing latitude or longitude. Nominatim is queried with the site name, address, region, and country, at most about once a second. A hit whose country does not match the site is dropped. Coordinates are rounded to 6 decimal places. Apply patches only latitude and longitude. |
| Conflicts & Queue | Stored mismatches. Resolve or ignore. |
| Sync History | Who ran which preview, apply, scan, or refresh, with counts and errors. |
| End of Life | Cisco devices, by PID (device type part number or model) and serial, against the Cisco Support EoX API v5. Shows end of sale, end of software maintenance, end of security support, last date of support, and the migration PID. Filters: past last date of support, within 12 months, OK, unknown. Results are cached in `netbridge_eox`. Refresh is manual and once a day from the scheduler when credentials exist. Requests are batches of 20 with a short pause. Optional preview writes only the `eox_*` custom fields. |

## Credentials

Settings → Vault has two forms. Values are stored in `data/vault/integrations.env` (mode 0600) because the install `.env` is mounted read-only. A key already set in `.env` is used when the integrations file has no value. The same keys may be set in `.env`:

- `CISCO_API_CLIENT_ID`
- `CISCO_API_CLIENT_SECRET`
- `FORTIMANAGER_URL`
- `FORTIMANAGER_TOKEN`

A blank field on save keeps the stored value. The API never returns the values, including Vault reveal. They are not written to the audit log or the process log. Test connection for Cisco gets an OAuth2 client-credentials token from `https://id.cisco.com/oauth2/default/v1/token` and looks up product `WS-C2960-24TC-L`. Test connection for FortiManager calls `POST /jsonrpc` for `/dvmdb/device` with `Authorization: Bearer`. If either pair is missing, the tab explains that and does not fail the rest of NetBridge.

WLC walks use the SNMPv2c community from `data/snmp/assignments.json` for that address when the profile is version `2c`, otherwise `SNMP_V2_COMMUNITY`. A controller that only has SNMPv3 is reported as not configured for this walk. SNMPv3 USM is not implemented in the walker.

## API

Reads are available to any signed-in user. Previews, applies, scans, conflict actions, and EoX refresh require Administrator or Engineer, same as device approval.

- `GET /api/v1/netbridge/summary`
- `GET /api/v1/netbridge/open-count`
- `GET /api/v1/netbridge/{stacks,addresses,controllers,access-points,fortimanager,sites,conflicts,history,eox}` with `page`, `page_size` (max 100), and `q`. Access points also take `model`. Conflicts take `status` (`open`, `resolved`, `ignored`, `all`). EoX takes `bucket` (`past`, `soon`, `ok`, `unknown`).
- `POST /api/v1/netbridge/{kind}/preview` and `POST /api/v1/netbridge/{kind}/apply` with `{previewId, confirm: true}`. `kind` is `stacks`, `addresses`, `controllers`, `access-points`, `sites`, or `eox`.
- `POST /api/v1/netbridge/access-points/scan`
- `POST /api/v1/netbridge/eox/refresh`
- `POST /api/v1/netbridge/conflicts/{id}` with `{action: resolve|ignore}`
- `POST /api/v1/discovery/roles` with `{ids, role}` stores the role used on approve.
- `POST /api/v1/settings/vault/integrations` and `POST /api/v1/settings/vault/integrations/test` (`target` is `cisco` or `fortimanager`). Administrator only.

List responses are `{rows, total, page, pageSize}`. The UI puts the total on the left and the pager on the right.

## Database

Tables live in the ie-config database (`DATABASE_URL`, PostgreSQL in the stack, SQLite if that variable is unset):

- `netbridge_jobs`
- `netbridge_conflicts`
- `netbridge_previews`
- `netbridge_aps`
- `netbridge_eox`

`scripts/upgrade.sh` runs `python -m ie_config.netbridge.migrate` inside ie-config, which is `Base.metadata.create_all`. Starting ie-config does the same. Existing rows are not dropped.

## What was tested, and what needs real devices

Tested here without a live network:

- pytest for the config-api, including matching, stack and address plans, the refuse-to-delete and refuse-to-rename checks, role persistence across a discovery refresh, vault save/reveal withholding, EoX parsing against a mocked Cisco API, conflict ignore, and a 5000-row GetBulk walk through the same BER codec.
- snmpsim 1.1.7 on UDP: 80 AireOS APs (name, model, serial, IP, CDP neighbour and port) plus one 9800-only name. `config-api/tests/test_netbridge_snmpsim.py`.
- vitest, including the Not in NetBox role dropdown and bulk role.
- `next build`.

Not tested against real equipment:

- A production Netdisco database (`device`, `device_module`, `device_ip`) and a real NetBox, including virtual chassis and custom fields on NetBox 4.6.
- A Catalyst 9800 or AireOS controller with thousands of APs, SNMPv3-only credentials, or CDP tables that use a different index than `CISCO-LWAPP-CDP-MIB`.
- Cisco's live EoX API, quotas, and product IDs that differ from the device-type model string. The daily job runs only when the scheduler is on and the client id and secret are saved.
- A real FortiManager. The client sends a bearer token to `/jsonrpc`. A manager that only accepts a session from `/sys/login/user` will not list devices until that login form is added.
- Nominatim from this host, including sites whose region name is not part of the result label.
- `upgrade.sh` against a running compose stack. The script's own self-test does not boot ie-config.
