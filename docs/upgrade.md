# Upgrading an existing install

This covers a server that was installed before the Postgres volume fix and the NetBox 4.6 token change. New installs do not need the volume copy. SNMP credentials in NetBox config contexts are described in [snmp-credentials.md](snmp-credentials.md). Devices with no `monitoring_snmp` context keep the `.env` SNMP values.

To remove the install and start fresh, see [uninstall.md](uninstall.md).

Prefer `./scripts/upgrade.sh` (add `--dry-run` to preview, or `--yes` to skip prompts). It fills missing `.env` secrets **before** any `docker compose` command, stops containers with `docker stop` on the `com.docker.compose.project` label (the containers stay so their volumes can be inspected), copies clusters only after they are identified, **rebuilds local images**, then starts and provisions the token.

Published host ports follow the firewall list: Prometheus 9090, Grafana 3000, Alertmanager 8086 (n8n holds 9093), NetBox 8092 (8080 is not reachable), SNMP exporter 9116, blackbox exporter 9115, Activepieces 8081, UI HTTP 18086, UI HTTPS 57400 when 443 is already taken, Telegraf host 57500, HTTP/3 on UDP 443. Netdisco and Oxidized stay on 5000 and 8888. `upgrade.sh` rewrites a port in `.env` only when it is still a previous default (`PORT_HTTP` 80, 8080, or 8086 becomes 18086; `PORT_NETBOX` 8444 or 8080 becomes 8092; `PORT_ALERTMANAGER` 9093 becomes 8086). A value such as `PORT_PROMETHEUS=19090` or `PORT_HTTPS=57400` is left in place, and the log names the firewall port so you can open the current one or edit `.env` yourself. Missing port keys are added. UI HTTPS is never moved.

`docker compose up -d` alone reuses the old `insightengine/*:local` images (`pull_policy: never`). Those images do not contain this upgrade until `docker compose build` has run. The script prints the ie-config image id before and after the build.

If you have not run `docker compose down` yet:

```bash
git pull
./scripts/upgrade.sh --dry-run
./scripts/upgrade.sh
```

`--dry-run` writes nothing. It prints each missing secret name, runs `docker compose config -q` (empty required variables are placeholders in that process only), and runs `scripts/migrate-pg-volumes.sh` without `--apply` so the catalog mapping is on screen. An old `.env` can omit `NETBOX_SUPERUSER_API_KEY`; `docker compose stop` would abort on that key, which is why the script backfills first and stops by label.

If the containers are already gone, `./scripts/upgrade.sh` still works: the migration identifies each anonymous volume by the database names in its catalog (`netbox` versus `ie_config`), not by volume name. When it cannot tell them apart it copies nothing.

Manual equivalent:

```bash
git pull
./install.sh --upgrade-env --no-start
docker ps -q --filter label=com.docker.compose.project=insightengine | xargs -r docker stop
./scripts/migrate-pg-volumes.sh            # prints catalog names, sizes, mtimes
./scripts/migrate-pg-volumes.sh --apply
docker compose build
docker compose pull --ignore-buildable || true
docker compose up -d
# wait until netbox is healthy
./scripts/provision-netbox-token.sh --apply
docker compose restart ie-config prometheus
docker compose up -d --force-recreate --no-deps oxidized netbox-device-types netbox-regions
# wait until the netbox-device-types container has exited, then:
docker compose up -d --force-recreate --no-deps netbox-component-backfill
```

`./install.sh --upgrade-env --no-start` is what `scripts/upgrade.sh` runs. `--upgrade-env` (also `--backfill-env`) accepts an existing `.env` that has no `.install-started` marker, which is every install made before that file existed. It accepts the file only when `PUBLIC_HOST`, `CLIENT_NAME`, `CLIENT_SLUG`, `INSTALL_DIR`, `NETBOX_DB_PASSWORD`, and `NETBOX_SECRET_KEY` are present and non-empty. It fills **missing or empty** required secrets and leaves every non-empty secret as it is. The one an older `.env` does not have is `NETBOX_SUPERUSER_API_KEY` (12 characters). The same pass fills any other required secret that is blank (`NETBOX_SUPERUSER_API_TOKEN`, the database passwords, Grafana, Activepieces, Netdisco). It writes `.install-started` only after that backfill. It does not change the host, client, ports, or certificates that already exist. A partial or corrupt `.env` is refused and left untouched. A plain `./install.sh` still refuses a `.env` that has no marker.

It also replaces the old Oxidized filter `status=active&tag=oxidized` with `status=active`, because that tag did not exist and NetBox answered 400. Any other non-empty filter is left alone. To limit backups to the tag after `scripts/seed-netbox.sh` has created it, set `OXIDIZED_NETBOX_FILTER='tag=oxidized&status=active'` (that text is left alone on later runs). `--dry-run` with `--upgrade-env` prints this plan and writes nothing.

`install.sh` chowns `.env` back to `SUDO_USER` when run with sudo. The setup service keeps that owner when it rewrites `.env`.

## What an older install already has

These checks were compared with the installer and compose file on `main` from before PR #6 (and with installs that predate `.install-started`). Each one either already matches that layout or is called out here.

| Assumption | Older install | What the upgrade does |
|---|---|---|
| `.install-started` contains `past-secret-generation` | Not written by installers before that file existed | `--upgrade-env` accepts a real `.env` without the marker and writes the marker after backfill. Plain `./install.sh` still refuses. |
| Compose project name `insightengine` | `name: insightengine` has been in `docker-compose.yml` since the first import, so containers are labeled `com.docker.compose.project=insightengine` | `migrate-pg-volumes.sh` reads compose config, then the file's `name:`, then that label. The checkout directory name is only the last fallback. `upgrade.sh` stops by that label. |
| Postgres service names `netbox-postgres` and `insightengine-postgres` | Same names before PR #6 | Inspect filters use those service labels. |
| Named volumes `insightengine_netbox-postgres-data` and `insightengine_insightengine-postgres-data` | Same volume keys, prefixed by the project name | The migration looks up that prefix, then any volume whose name ends with the key. |
| Cluster directory | The named volume was mounted at `/var/lib/postgresql`, so the real cluster is the anonymous volume at the image path `/var/lib/postgresql/data` | Inspect uses that mount. The copy lands in `pgdata/` inside the named volume, which is where the new `PGDATA` points. |
| Secret files | `secrets/prometheus/netbox.token`, `secrets/oxidized/netbox.token`, and `secrets/cust-exporter/netbox.token`. There is no `secrets/netbox/` directory. The old file is the 40-character `NETBOX_SUPERUSER_API_TOKEN` (v1 `Authorization: Token`), not `nbt_<key>.<secret>` | `provision-netbox-token.sh` reads and writes those three paths. `lib-netbox-auth.sh` sends `Token` when the file does not start with `nbt_`, and provisions a v2 token when that header is rejected. |
| `NETBOX_SUPERUSER_API_KEY` | Absent | Backfill adds it and does not replace a non-empty `NETBOX_SUPERUSER_API_TOKEN`. |
| Certificates, host, client, ports | Already set | Left as they are when the files and values exist. |
| `COMPOSE_PROJECT_NAME` in `.env` | Usually unset | Not required. The compose file's `name:` is enough. |
| `OXIDIZED_NETBOX_FILTER` | Often `status=active&tag=oxidized` | Replaced with `status=active` only when empty or exactly that old default. Any other value stays. |

## Postgres data is in an anonymous volume

`postgres:17.9` stores the cluster in `/var/lib/postgresql/data`. The old compose file mounted the named volume at `/var/lib/postgresql`, so Docker kept the real files in an anonymous volume. `docker compose down` drops the container and leaves that volume behind. The next `up` created an empty database: NetBox migrated from zero and the ie-config admin was gone. Netdisco was not affected (its PostgreSQL 18 image is mounted at `/var/lib/postgresql` on purpose).

The compose file now mounts `netbox-postgres-data` and `insightengine-postgres-data` at `/var/lib/postgresql/data` and sets `PGDATA=/var/lib/postgresql/data/pgdata`.

`scripts/migrate-pg-volumes.sh` resolves the compose project in this order: `--project`, a shell `COMPOSE_PROJECT_NAME`, `COMPOSE_PROJECT_NAME` in `.env`, `docker compose config --format json` (the `.name` field), the top-level `name:` in `docker-compose.yml` (`insightengine`), then the `com.docker.compose.project` label on a postgres container. The checkout directory name is only the last fallback. It refuses to copy while a postgres container is running. It skips a destination that already has `pgdata/PG_VERSION` unless you pass `--force` (the previous `pgdata` is renamed to `pgdata.bak.<time>` inside the named volume). Source volumes are mounted read-only and are never deleted.

That skip is why an empty `users` table can survive the migration. `upgrade.sh` does not write users and does not restore `data/setup`. The script copies a whole cluster; it does not look for rows in `users`. A volume is treated as ie-config when the catalog contains the database name `ie_config` (or `insightengine`). Postgres init creates that database and role on an empty volume (`config/insightengine-postgres/init/01-ie-config.sh`) and does not insert users, so a brand-new cluster still matches.

The users were not removed by the copy. They were left behind earlier. `docker compose down` drops the container and orphans the anonymous volume that held the real cluster. The next `up` initializes an empty cluster on the new named volume (`pgdata/PG_VERSION` exists, `users` is empty). A later migrate sees that cluster and skips, so it does not restore the older anonymous volume. Setup can still say `complete`: that flag is `data/setup/config.json` on the host, not a row in Postgres.

`sudo ./scripts/reset-admin-password.sh` creates the Administrator when `users` is empty. The setup service, on startup and on `GET /setup/state`, asks ie-config `GET /internal/user-count`. If the state is `complete` and the count is 0, it reopens `unconfigured` / `step=admin` and keeps the client name and mode. If ie-config cannot be asked, it logs that the state was left unchanged and does not flip the file. ie-config logs the same mismatch when it can read `data/setup/config.json`.

Anonymous volumes from this bug only carry the label `com.docker.volume.anonymous`. The script does not pair them by name. With the containers stopped but not removed, it reads the volume mounted at `/var/lib/postgresql/data` from `docker inspect` and checks that the catalog agrees. After `down`, it reads `global/` in each volume for the database and role names (`netbox` versus `ie_config` / `insightengine`). A netdisco catalog is ignored. If a volume cannot be identified, or two volumes match the same service, it exits and copies nothing. Override with `--map netbox=<volume>,insightengine=<volume>` only when the dry-run catalog lines match what you expect; a map that contradicts the catalogs is refused.

The dry-run prints, for every candidate, the volume id, PostgreSQL version, size, `PG_VERSION` mtime, catalog names, and whether a stopped container mount selected it.

Activepieces already mounted its volume at `/var/lib/postgresql/data`. Do not point `PGDATA` at a subdirectory for that service or you will hide the existing cluster. Netdisco's PostgreSQL 18 mount is already correct. `netdisco-db-role` mounts a tmpfs on `/var/lib/postgresql` so that one-shot does not leave a new anonymous volume on every recreate.

An older Netdisco cluster created with `POSTGRES_USER=netdisco` has superuser role `netdisco` and no `postgres` role. `config/netdisco/align-db-role.sh` connects on the local socket as `postgres`, then as `NETDISCO_DB_USER`, then as any other login role with `rolsuper`. It sets that app role's password to `NETDISCO_DB_PASS`. If the app role is the superuser, it changes only the password and does not remove superuser. `netdisco-db-init`, the web and backend, the scheduler, and ie-config's `NETDISCO_DATABASE_URL` already use `NETDISCO_DB_USER` and `NETDISCO_DB_PASS`, not the `postgres` role. The postgres healthcheck is `pg_isready -U postgres`, which does not log in, so a missing `postgres` role does not fail it.

`scripts/test-pg-persistence.sh` starts only the two Postgres services in a throwaway compose project and a subnet that is not `10.50.0.0/24`, writes a row, runs `down` then `up -d`, and checks the row.

## NetBox API token

NetBox 4.6 creates the superuser token only when **both** `SUPERUSER_API_KEY` (12 characters) and `SUPERUSER_API_TOKEN` (40 characters) are set, and only while it is creating the user. Clients send:

```text
Authorization: Bearer nbt_<key>.<secret>
```

`POST /api/users/tokens/provision/` on 4.6.3 returns `key` (12 characters) and `token` (the 40-character secret, **without** the `nbt_` prefix). `scripts/provision-netbox-token.sh` joins those into `nbt_<key>.<secret>`. If it cannot store the token, it deletes the one it just created so a retry does not leave an orphan. A later run that already authenticates does not create another token.

The device-type importer and the region importer re-read `secrets/prometheus/netbox.token` on every retry. Recreate those one-shots after provisioning so they are not still inside an old wait loop. The component backfill runs after the device-type importer has exited, because it reads the templates that importer wrote:

```bash
docker compose up -d --force-recreate --no-deps netbox-device-types netbox-regions
# wait until the netbox-device-types container has exited, then:
docker compose up -d --force-recreate --no-deps netbox-component-backfill
```

Also restart `ie-config` and `prometheus`, and recreate `oxidized`, so they read the new file.

## Oxidized with no devices

The default filter is `status=active`, so approved discoveries and devices added by hand are backed up. With zero devices NetBox returns an empty list. Oxidized treats that as "source returns no usable nodes" and may never open port 8888. `config/oxidized/oxidized-run.sh` retries Oxidized and, while it is down, answers `GET /nodes` with `[]` so the container stays healthy.

## Activepieces

Workers wait until `activepieces-app` is healthy, so they do not all insert `piece_metadata` at the same moment as the app. A duplicate-key error on that table during a cold start is benign: Activepieces treats it as "already migrated" and continues.

## `.env` ownership

`sudo ./install.sh` chowns `.env` back to `SUDO_USER` and leaves it mode 600. The setup service copies the previous owner and mode when it rewrites `.env`. If a previous setup run already left the file as root, run `sudo ./install.sh --no-start` once to give it back.
