# Upgrading an existing install

This covers a server that was installed before the Postgres volume fix and the NetBox 4.6 token change. New installs do not need the volume copy.

Do this with the stack stopped, and do not start it until the volume copy has finished. `./install.sh` without `--no-start` would start the containers first.

```bash
docker compose down
git pull
./install.sh --no-start
./scripts/migrate-pg-volumes.sh            # dry-run
./scripts/migrate-pg-volumes.sh --apply
docker compose up -d
# wait until `docker compose ps` shows netbox healthy
./scripts/provision-netbox-token.sh            # dry-run
./scripts/provision-netbox-token.sh --apply    # does not print the token
docker compose restart ie-config prometheus
docker compose up -d --force-recreate --no-deps oxidized netbox-device-types
```

`./install.sh --no-start` fills **missing or empty** required secrets and leaves every non-empty secret as it is. The one an older `.env` does not have is `NETBOX_SUPERUSER_API_KEY` (12 characters). The same pass fills any other required secret that is blank (`NETBOX_SUPERUSER_API_TOKEN`, the database passwords, Grafana, Activepieces, Netdisco). It also replaces the old Oxidized filter `status=active&tag=oxidized` with `status=active`, because that tag did not exist and NetBox answered 400. To limit backups to the tag after `scripts/seed-netbox.sh` has created it, set `OXIDIZED_NETBOX_FILTER='tag=oxidized&status=active'` (that text is left alone on later runs).

`install.sh` chowns `.env` back to `SUDO_USER` when run with sudo. The setup service keeps that owner when it rewrites `.env`.

## Postgres data is in an anonymous volume

`postgres:17.9` stores the cluster in `/var/lib/postgresql/data`. The old compose file mounted the named volume at `/var/lib/postgresql`, so Docker kept the real files in an anonymous volume. `docker compose down` drops the container and leaves that volume behind. The next `up` created an empty database: NetBox migrated from zero and the ie-config admin was gone. Netdisco was not affected (its PostgreSQL 18 image is mounted at `/var/lib/postgresql` on purpose).

The compose file now mounts `netbox-postgres-data` and `insightengine-postgres-data` at `/var/lib/postgresql/data` and sets `PGDATA=/var/lib/postgresql/data/pgdata`.

`scripts/migrate-pg-volumes.sh` reads `COMPOSE_PROJECT_NAME` from `.env` when you do not pass `--project` (a shell `COMPOSE_PROJECT_NAME` or `--project` still wins). It refuses to copy while a postgres container is running. It skips a destination that already has `pgdata/PG_VERSION` unless you pass `--force`. It does not delete the anonymous volume unless you pass `--remove-source` after you have logged in and confirmed the data is there. A second `--apply` is a no-op.

Activepieces already mounted its volume at `/var/lib/postgresql/data`. Do not point `PGDATA` at a subdirectory for that service or you will hide the existing cluster. Netdisco's PostgreSQL 18 mount is already correct. `netdisco-db-role` mounts a tmpfs on `/var/lib/postgresql` so that one-shot does not leave a new anonymous volume on every recreate.

`scripts/test-pg-persistence.sh` starts only the two Postgres services in a throwaway compose project and a subnet that is not `10.50.0.0/24`, writes a row, runs `down` then `up -d`, and checks the row.

## NetBox API token

NetBox 4.6 creates the superuser token only when **both** `SUPERUSER_API_KEY` (12 characters) and `SUPERUSER_API_TOKEN` (40 characters) are set, and only while it is creating the user. Clients send:

```text
Authorization: Bearer nbt_<key>.<secret>
```

`POST /api/users/tokens/provision/` on 4.6.3 returns `key` (12 characters) and `token` (the 40-character secret, **without** the `nbt_` prefix). `scripts/provision-netbox-token.sh` joins those into `nbt_<key>.<secret>`. If it cannot store the token, it deletes the one it just created so a retry does not leave an orphan. A later run that already authenticates does not create another token.

The device-type importer re-reads `secrets/prometheus/netbox.token` on every retry. Recreate that one-shot after provisioning so it is not still inside an old wait loop:

```bash
docker compose up -d --force-recreate --no-deps netbox-device-types
```

Also restart `ie-config` and `prometheus`, and recreate `oxidized`, so they read the new file.

## Oxidized with no devices

The default filter is `status=active`, so approved discoveries and devices added by hand are backed up. With zero devices NetBox returns an empty list. Oxidized treats that as "source returns no usable nodes" and may never open port 8888. `config/oxidized/oxidized-run.sh` retries Oxidized and, while it is down, answers `GET /nodes` with `[]` so the container stays healthy.

## Activepieces

Workers wait until `activepieces-app` is healthy, so they do not all insert `piece_metadata` at the same moment as the app. A duplicate-key error on that table during a cold start is benign: Activepieces treats it as "already migrated" and continues.

## `.env` ownership

`sudo ./install.sh` chowns `.env` back to `SUDO_USER` and leaves it mode 600. The setup service copies the previous owner and mode when it rewrites `.env`. If a previous setup run already left the file as root, run `sudo ./install.sh --no-start` once to give it back.
