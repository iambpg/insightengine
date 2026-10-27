# ie-config architecture

`ie-config` is a small FastAPI process. It is the only container that can change monitoring configuration and ask for a container restart. It is reached through Caddy at `/api/v1` after the setup gate (the same gate as the UI). The bootstrap route is not published through Caddy.

## What it can do

- Read and write the config files listed in `config-api/apps.yml`. Paths are relative to `CONFIG_ROOT`. The resolver rejects absolute paths, `..`, and anything that realpath sends outside that root.
- Validate with the binaries copied into the image (promtool, amtool, snmp_exporter `--dry-run`, blackbox_exporter `--config.check`, caddy `validate` / `adapt`). Telegraf is TOML syntax only: `telegraf --test` contacts devices, so it is not run. If a binary is missing, the API says so in `tool` and falls back to syntax.
- Reload over HTTP on the monitoring network (`/-/reload` on Prometheus, Alertmanager, blackbox, SNMP exporter). Caddy reload runs `caddy adapt` and POSTs the JSON to the admin `/load` API. An empty POST is not sent. If adapt cannot run, the response says to restart.
- Restart a container only when its name is in the registry (or the fixed names `ie-setup`, `ie-docker-proxy`, `ie-config`, `ie-config-docker-proxy`). The call goes to `ie-config-docker-proxy`, a second tecnativa proxy. It allows container list/inspect and restart. `POST=1` on that proxy also enables DELETE in the proxy itself; start, stop, exec, images, networks, volumes, and secrets are set to 0. This is still a privileged Docker API. Only an Administrator can call restart, every call is audited, and the service is not published on the host.

## Data

Users, sessions, the append-only audit log, reload state, and discovery candidates are rows in database `ie_config` on `insightengine-postgres` (its own role). The init script `config/insightengine-postgres/init/01-ie-config.sh` runs only when that Postgres volume is first created. An existing volume does not pick up the role; create it by hand or recreate the volume.

Passwords are argon2id. Session tokens are stored as SHA-256. History files live under `data/config-history` (mode 0600) and are not returned unmasked.

Secrets: files marked `secret_file` are never read. Values inside editable files are masked as described in `docs/settings-api.md` and restored on save. Netdisco's rendered `deployment.yml` (with SNMP passwords substituted from an allow-list of environment variables) is written into the `netdisco-local` volume, mode 0600, and is not a registry file, so GET never returns it.

## Mounts

Editable configs use directory mounts. A bind mount of a single file keeps the old inode across an atomic rename, so Prometheus would reload the previous file. `extra.py` and `plugins.py` stay file mounts; applying them restarts NetBox. The whole `/etc/netbox/config` directory is not mounted, because that would hide `configuration.py`.

ie-config runs as root because it writes those host directories. It has no published port.

## Discovery loop

A thread (disable with `IE_CONFIG_SCHEDULER=0`) renders the Netdisco deployment, and every `interval_hours` (default 6) syncs prefixes and refreshes the unapproved list. `scripts/netdisco-scheduler.sh` in the Netdisco image reads `scan-prefixes.txt` and runs `netdisco-do` with the CIDR as an argument (no `eval`). Netdisco's web and backend wait until ie-config is healthy so the volume has a deployment file. If ie-config is down, Netdisco waits.
