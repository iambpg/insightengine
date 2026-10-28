# Upgrading an existing install

This covers a server that was installed from `main` before the Postgres volume fix (the machine in the 2026-10-28 test). New installs do not need the volume copy.

## Postgres data is in an anonymous volume

`postgres:17.9` stores the cluster in `/var/lib/postgresql/data`. The old compose file mounted the named volume at `/var/lib/postgresql`, so Docker kept the real files in an anonymous volume. `docker compose down` drops the container and leaves that volume behind. The next `up` created an empty database: NetBox migrated from zero and the ie-config admin was gone. Netdisco was not affected (its PostgreSQL 18 image is mounted at `/var/lib/postgresql` on purpose).

The compose file now mounts `netbox-postgres-data` and `insightengine-postgres-data` at `/var/lib/postgresql/data` and sets `PGDATA=/var/lib/postgresql/data/pgdata`.

On the server that already has data:

```bash
docker compose down
git pull   # this change
./scripts/migrate-pg-volumes.sh            # dry-run: prints the volumes it would copy
./scripts/migrate-pg-volumes.sh --apply    # copies into the named volume's pgdata/
docker compose up -d
```

The script refuses to copy while a postgres container is running. It skips a destination that already has `pgdata/PG_VERSION` unless you pass `--force`. It does not delete the anonymous volume unless you pass `--remove-source` after you have logged in and confirmed the data is there. Run it once; a second `--apply` is a no-op.

Activepieces already mounted its volume at `/var/lib/postgresql/data`. Do not point `PGDATA` at a subdirectory for that service or you will hide the existing cluster. Netdisco's PostgreSQL 18 mount is also already correct.

`scripts/test-pg-persistence.sh` starts only the two Postgres services in a throwaway compose project, writes a row, runs `down` then `up -d`, and checks the row. It does not touch a real install's volumes.

## NetBox API token

NetBox 4.6 creates the superuser token only when **both** `SUPERUSER_API_KEY` (12 characters) and `SUPERUSER_API_TOKEN` (40 characters) are set, and only while it is creating the user. Clients send:

```text
Authorization: Bearer nbt_<key>.<secret>
```

v1 tokens (`Authorization: Token <40 hex>`) are deprecated in 4.6 and removed in 5.0. `install.sh` generates both values and writes `nbt_<key>.<secret>` into:

- `secrets/prometheus/netbox.token` (Prometheus http_sd, ie-config, the device-type importer)
- `secrets/oxidized/netbox.token`
- `secrets/cust-exporter/netbox.token`

If you restored a database whose admin user already exists, the entrypoint will not create a token. After NetBox is healthy:

```bash
./scripts/provision-netbox-token.sh            # says whether the current file works
./scripts/provision-netbox-token.sh --apply    # provisions a v2 token; does not print it
```

Then restart ie-config, Prometheus, and Oxidized. A token file that already returns HTTP 200 is left unchanged.

## `.env` ownership

`sudo ./install.sh` used to leave `.env` owned by root, mode 600, so the original user could not run `docker compose`. The installer now chowns `.env` back to `SUDO_USER` and keeps mode 600. Secret files stay owned by the container uid. Re-run `sudo ./install.sh` on a half-finished install (it resumes after secret generation) to fix the owner without regenerating secrets.
