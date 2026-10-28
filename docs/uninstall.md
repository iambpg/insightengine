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
| `--backup-first` | Before deletion, write `netbox.sql` and `ie_config.sql` under `~/insightengine-backups/uninstall-<time>/` (or `UNINSTALL_BACKUP_DIR`). The folder is outside the repository. If the dump fails, nothing is removed. |

The script does not print secrets. When it finishes it prints `sudo ./install.sh --public-host <host>` using `PUBLIC_HOST` from `.env`. If Docker is not running it warns and still removes the installer files.
