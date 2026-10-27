# Testing discovery (NetBox, Prometheus, Netdisco)

After `./install.sh` and the first-run page (client name, administrator, new install):

1. NetBox is seeded with a tenant, a region, the device roles the Prometheus jobs use (`access-switch`, `core-switch`, `distribution-switch`, `sdwan`, `hub`, `core-firewall`, `wireless-controller`), and the tag `ie-scan`.
2. Add a device in NetBox with status **active**, one of those roles (or any other role: the catch-all jobs still pick it up), and a primary IPv4 address. Within about 5–10 minutes Prometheus http_sd refreshes (`refresh_interval: 5m`) and the device is an ICMP target and an SNMP target.
3. Add a prefix and tag it `ie-scan` (or turn on `scan_all_active_prefixes` in Settings → Netdisco → `sync.yml`). ie-config writes the prefix list into the Netdisco volume. The scheduler runs `netdisco-do discover`, `macsuck`, and `arpnip` on that interval (default 6 hours) and when you use the **Scan prefixes now** action.
4. A device Netdisco has recorded that is not in NetBox shows up at `GET /api/v1/discovery/unapproved`. Approve creates it in NetBox; step 2 then monitors it.

`scripts/e2e-discovery.sh` does steps 2 and 3 against the local APIs using a documentation address (`203.0.113.10` unless you override `IE_E2E_IP`). It checks that Prometheus **lists** the target. It does not require the `up` metric to be 1, because that address does not answer ICMP. Set `IE_E2E_REQUIRE_UP=1` only when the address is a real device.

The script was not run against real devices in this change. It also does not insert a row into Netdisco, so it does not prove the unapproved list by itself. That list fills when Netdisco's `device` table has an IP NetBox does not.

SNMP module and auth for a role come from `config/discovery/module-map.yml`. A device custom field `snmp_module` or `snmp_auth`, when set, overrides the map.
