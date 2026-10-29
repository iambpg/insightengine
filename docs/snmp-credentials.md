# SNMP credentials

Devices do not have their own SNMP field. A NetBox **config context** holds a JSON object named `monitoring_snmp`. NetBox applies its own scoping (site group, site, region, role, platform, tenant) and weight. The rendered `config_context` on `GET /api/dcim/devices/<id>/` is what InsightEngine reads. The most specific context with the highest weight is already chosen by NetBox.

```json
{"monitoring_snmp":{"version":"3","port":161,"security_name":"<v3-user>","security_level":"authPriv","auth_protocol":"SHA","auth_passphrase":"<auth-pass>","priv_protocol":"AES","priv_passphrase":"<priv-pass>"}}
```

`version` is `2c` or `3`. `port` defaults to 161. Version `2c` uses `community`. Version `3` uses `security_name`, `security_level` (`noAuthNoPriv`, `authNoPriv`, or `authPriv`), `auth_protocol`, `auth_passphrase`, `priv_protocol`, `priv_passphrase`, and optional `context_name`.

When a device's rendered context has no `monitoring_snmp` object, Prometheus and Netdisco keep using the `.env` values (`SNMP_V2_COMMUNITY`, `SNMP_V3_USER` / `SNMP_V3_USERNAME`, `SNMP_V3_AUTH_PASSWORD`, `SNMP_V3_PRIV_PASSWORD`) and the existing auth names `ntt_snmpv3_auth` and `ie_snmp_v2`.

ie-config reads each active device with the service token, hashes the resolved profile, and:

- writes `data/snmp/auth-by-ip.yml` (addresses and auth names only) for the NetBox `prometheus-devices` HTTP SD source, which sets `__meta_netbox_snmp_auth`; Prometheus already copies that label to `__param_auth`
- writes `data/snmp/snmp.runtime.yml` (mode 0600) with one `auths:` entry per distinct profile (only the generated auths; the exporters layer it over the committed `snmp.yml`, see `config/snmp/snmp-exporter-run.sh`) and reloads the snmp-exporters via `POST /-/reload`
- adds Netdisco `device_auth` entries with `only:` set to those addresses, ahead of the `.env` fallback entry

A sync runs every 5 minutes and right after a save through Settings → SNMP. A context edited directly in NetBox is picked up at the next pass. The "test device" action does a v2c GET from ie-config; for v3 it asks an exporter to scrape the device's `system` module with the generated auth, so a v3 profile saved less than a few seconds ago can answer `auth_not_loaded` until the sync has finished.

`snmp_exporter` expands `${VAR}` in `username`, `password` and `priv_password` only (with `--config.expand-environment-variables`). It does not expand `community`, so the exporter start script resolves `community: ${SNMP_V2_COMMUNITY}` from its environment before starting. A `$` in a generated community is not escaped for that reason.

`snmp/out/snmp.yml` stays free of literal communities and passphrases. The runtime file is not in git (`data/` is ignored).

## Where the secrets live

Settings → SNMP can use either storage:

| Mode | Config context | Secret values |
|---|---|---|
| Context (default) | The full `monitoring_snmp` object | In NetBox, returned in plain text by the config-context API |
| File | `{"monitoring_snmp":{"profile":"<name>"}}` only | `data/snmp/profiles.json`, mode 0600, on this host |

In both modes `data/snmp/profiles.json` (mode 0600) keeps a copy of the secrets saved through Settings → SNMP, so that a later save with blank secret fields keeps the stored value. It is never served. Profiles that exist only as a hand-made config context are not copied there.

NetBox deep-merges the config contexts that match a device, so keys from a lower-weight context survive under a higher-weight one (a `{"profile": "x"}` context over a full v3 context still contains `version`, and the full profile wins). Give every `monitoring_snmp` context the same shape and use the weight only to pick the winner.

Generated files that hold secrets, all mode 0600 and root-owned: `data/snmp/profiles.json`, `data/snmp/assignments.json` (the input for the Netdisco `device_auth` rendering), `data/snmp/snmp.runtime.yml`. `data/snmp/auth-by-ip.yml` (0644) holds only IP to auth names. A device whose `monitoring_snmp` fails validation is logged by device id (never by value), skipped in the generated files, and keeps the `.env` fallback; the sync of every other device carries on. Prometheus reads the http_sd list every 5 minutes, so a removed or renamed auth can answer `400` for up to that long.

The Settings API never returns a community or passphrase. Saving a profile sends those fields once. Leaving them blank on a later save keeps the stored value. They are not written to logs.

Give **config context view** only to NetBox administrators and the InsightEngine service account. Anyone else who can view config contexts can read the secrets when they are stored in the context. The file mode avoids that: the context is a name, and the values stay on the monitoring host.

## UDP 161

SNMP uses **UDP port 161** on the device (the `port` field can change it). Exporters and Netdisco must be allowed to send UDP to that port, and the device ACL must allow the monitoring host's address. TCP is not used for these polls. A test from Settings → SNMP sends one SNMPv2c GET for `sysDescr.0`, or asks an snmp-exporter to use the v3 auth name. The API result does not include the credential.
