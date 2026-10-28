# Removing an install

`scripts/uninstall.sh` deletes one InsightEngine install so `./install.sh` can create it again. The default is a dry-run. It does not delete the git checkout, git-tracked files, or Docker resources that belong to another project (for example k3s).

```bash
./scripts/uninstall.sh
./scripts/uninstall.sh --apply
sudo ./scripts/uninstall.sh --backup-first --apply --yes
```

`--apply` removes nothing until you type the client slug from `.env` or the word `DELETE`. `--yes` is the non-interactive confirmation. A pipe with no `--yes` is refused.

The dry-run lists:

- containers labelled `com.docker.compose.project` for this compose project
- networks with that label
- named and anonymous volumes with that label, and anonymous volumes still mounted by those containers (the old Postgres layout keeps the cluster in an anonymous volume at `/var/lib/postgresql/data`)
- local images `insightengine/*:local` and `insightengine-ui:local`
- installer files: `.env`, `.install-started`, generated files under `certs/`, `secrets/`, `data/`, `migration/migrate.conf`, `migration/imported/`, and `config/netdisco/nd-site-local/` (not `deployment.yml.example`)

`certs/.gitkeep`, `secrets/.gitkeep`, and `data/migration/.gitkeep` stay. Unlabelled anonymous volumes are left alone, because they cannot be told apart from other software on the host.

| Flag | Effect |
|---|---|
| `--keep-images` | Do not delete the local `insightengine` images. |
| `--keep-certs` | Do not delete `certs/`. |
| `--keep-backups` | Do not delete `data/migration/`, `migration/imported/`, or `*.dump`. |
| `--backup-first` | Before deletion, write `netbox.sql` and `ie_config.sql` under `~/insightengine-backups/uninstall-<time>/` (or `UNINSTALL_BACKUP_DIR`). The folder is outside the repository and owner-only (0700, files 0600). If the dump fails, nothing is removed. |
| `--files-only` | Delete only the installer files and never touch Docker. Use it only when you have removed the containers and volumes yourself. |

The script does not print secrets. When it finishes it prints `sudo ./install.sh --public-host <host>` using `PUBLIC_HOST` from `.env`.

Things to know:

- Run it with `sudo`. The installer's `secrets/` and `data/` files are root-owned. As a normal user the dry-run warns that its list is incomplete, and `--apply` refuses before deleting anything.
- Under `sudo`, `~` is `/root`, so `--backup-first` writes to `/root/insightengine-backups/` unless you set `UNINSTALL_BACKUP_DIR`. The dumps hold the NetBox and `ie_config` databases (including stored credentials): copy them off the host. Media, reports and scripts volumes and the files under `secrets/` are not in the dump.
- If Docker is not usable (daemon stopped, no permission, command missing) `--apply` refuses, because deleting only `.env` and `secrets/` would leave Postgres volumes that still hold the old passwords and the next install would not start. Start Docker, or pass `--files-only` if you have already removed the volumes.
- Removal goes object by object. An image or network that something else still uses is skipped with a warning and the exit status is 1. A volume that cannot be removed keeps the files, so run the script again once the volume is free.
- Anonymous volumes carry no compose label. They are removed only while a container of this project still mounts them. Run this script before `docker compose down`; afterwards they are orphans that only `docker volume prune` can find, and that also hits other software's unused volumes.
- Scoping is by compose project name. A different stack that was started with the same project name (`insightengine`) on the same host is treated as this one; use `--project` to pick the right name.
