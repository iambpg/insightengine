# InsightEngine monitoring stack — review bundle

**One clone is the product.** `git clone` this repository and run `./install.sh`. The customer UI is the Next.js app under `ui/`. `install.sh` builds it, you open `https://<PUBLIC_HOST>/`, the first-run page is `/setup/`, and after setup the same address is the UI. You do not clone a second repository.

It is a Docker Compose bundle for **one install per client**, sized (by estimate) for **~20,000 devices per client**
(switches, APs, SD-WAN, routers, WLCs; ~5,500–6,000 APs per WLC).

> **Important assumption.** The middle of the compose file you pasted was cut off. NetBox, Grafana, Alertmanager, blackbox,
> Telegraf and the old automation tool were **reconstructed from the standard upstream images and docs**, not copied from your
> file. Compare every service with your real file before you use this. Everything I could not know is a `TODO(Phindani)`.
>
> **Nothing was tested on real devices.** Every number labelled *estimate* is a planning estimate, not a measurement.

## 1. Contents

| Path | What it is |
|---|---|
| `install.sh` | **Non-interactive** installer: prerequisites, private CA + certificates, `.env` with generated secrets (`CLIENT_NAME=unconfigured`), data folders, builds/pulls and starts the stack. Asks **nothing**. |
| `.env.example` | Every variable, with defaults (sizing values are estimates). The only env file committed. |
| `docker-compose.yml` | The stack (fixed project name `insightengine`). Optional parts are behind profiles. |
| `setup/` | The first-run **setup service** (`server.py`, standard library only), its plain-HTML page (`static/`) and stub-based tests (`tests/`). |
| `config-api/` | `ie-config`: Settings API, validation, reload, discovery. |
| `reference/ntt-real-stack/` | Sanitized copy of the running stack used to reconcile this bundle. |
| `docs/setup-api.md` | The setup service HTTP API (endpoints, JSON, token, states) for the UI developer. |
| `docs/settings-api.md` | Settings and discovery API implemented by `config-api/` (`ie-config`). |
| `docs/fleet-api.md` | Device, site, alert, summary and health routes the customer UI calls. |
| `docs/snmp-credentials.md` | SNMP credentials in NetBox config contexts, with the `.env` values as the fallback. |
| `ui/` | Customer UI (Next.js). `./install.sh` builds `insightengine-ui:local` from `ui/Dockerfile` (port 8080, `GET /healthz`, `NEXT_PUBLIC_IE_API_MODE=live`). Empty `IE_UI_IMAGE` means that build. |
| `config/` | Prometheus, Alertmanager, Caddy, blackbox, Loki, Grafana provisioning, Telegraf, Oxidized, alert relay, Netdisco. `config/ui-placeholder/` is only a copy of the setup-redirect sample. |
| `snmp/`, `trapd/` | SNMP generator input / exporter skeleton / MIBs; snmptrapd image (traps → Alertmanager + Loki). |
| `scripts/` | `validate.sh`, `migrate.sh`, `prom-history.sh`, `set-secret.sh`, `seed-netbox.sh`, `uninstall.sh`. |
| `migration/` | `migrate.conf.example`; the real `migrate.conf` is written by the setup service (mode 600, git-ignored). |

## 2. Install and first run

### 2.1 Install (no questions)

```bash
git clone <this-repo> insightengine && cd insightengine
sudo ./install.sh --public-host monitor.example.com      # or: INSTALL_PUBLIC_HOST=... sudo -E ./install.sh
```

To wipe this install and start over, see [docs/uninstall.md](docs/uninstall.md) (`./scripts/uninstall.sh` lists what it would remove; deletion needs `--apply`).

`install.sh` flags: `--public-host HOST` (default: first IP / host name of this machine — the value goes into the TLS certificate and `PUBLIC_HOST`),
`--alt-ports` / `--default-ports` (default: **automatic** — every published host port is probed with `ss`, `lsof`, Docker's published ports, and, when `iptables` is readable, NAT rules. A Kubernetes loadbalancer DNAT for this host's :80 or :443, such as k3s Traefik, is invisible to `ss`; that port is treated as taken and the installer says why. A free default is kept. A busy port is replaced on its own: its preferred alternative, then the next free port. One busy port does not move the others. `--default-ports` stops if a default is busy. `--alt-ports` starts from the preferred alternatives), `--no-start` (prepare files only), `--fix-perms`, `--help`.
Caddy's global `default_sni` is `PUBLIC_HOST`. A browser opened by IP sends no SNI; that default makes every `https://PUBLIC_HOST:PORT` site (the setup URL and the other published app ports) present the install certificate. `fallback_sni` is not used: it applies only when SNI is present and matches nothing.
If `.env` exists and `.install-started` contains exactly `past-secret-generation`, a later run resumes at certificates, image build, and start. It does not regenerate or print secrets, and it does not rewrite `.env`, ports, or secret files. If `.env` exists without that marker, a plain `./install.sh` stops and leaves `.env` untouched. `./install.sh --upgrade-env` is the upgrade path for that pre-marker file: it checks the file is a real install, fills only missing secrets, then writes the marker. `--dry-run` with `--upgrade-env` prints the plan and writes nothing. Generated values live only in `.env` (mode 600) and `secrets/`. `sudo ./install.sh` chowns `.env` back to `SUDO_USER` and leaves it mode 600. Each key is written once.
The chosen ports are the ones Caddy listens on and the ones in Prometheus `--web.external-url`, Alertmanager `--web.external-url`, Grafana `root_url`, NetBox, and the setup URL printed at the end. `scripts/smoke.sh` (after the stack is up; it does not start it) waits and prints the last 15 log lines of any container that is not healthy.
Run as root so secret files are `0400` and owned by the container user (otherwise `0644` + a warning; fix later with `sudo ./install.sh --fix-perms`).

It does **not** ask for the client or for new-vs-move: it writes `CLIENT_NAME='unconfigured'`, `CLIENT_SLUG='unconfigured'`, creates
`secrets/setup/token`, builds the local images, pulls the others and runs `docker compose up -d`.

### 2.2 First run (browser)

1. Open `https://<PUBLIC_HOST>[:PORT_HTTPS]/setup/` (import `certs/ca.crt` in the browser to avoid the certificate warning). While the setup state is not
   `complete`, Caddy sends `/` (everything except `/setup/*` and the other service ports) to this page.
2. Paste the **setup token** (read it on the server: `sudo cat secrets/setup/token`; it is kept in the page's memory only).
3. **Which client is this server for?** Type the name → "Save and apply". The setup service renders `CLIENT_NAME`/`CLIENT_SLUG` into `.env` and runs
   `docker compose up -d` for this project, which recreates the containers with the client name (`<service>-<slug>` container names, Prometheus `client` label, Grafana
   folder, Alertmanager titles, …). Estimate: a few minutes.
4. **First administrator.** Email and a password (or generate one, shown once on the page). It is not written to the setup log. This is the Settings login.
5. **New install** (finish) or **Move from the old stack, keeping data** (§8): old-stack paths → read-only preflight → confirm → run with progress and log →
   **keep Prometheus history or start fresh**.
6. State becomes `complete`; `/` now shows the Next.js UI built from `ui/`. The page redirects to `/setup/` while the state is not `complete`.
7. `install.sh` writes a NetBox 4.6 v2 API token (`nbt_<key>.<secret>`, sent as `Authorization: Bearer`) into `secrets/prometheus/netbox.token` and `secrets/oxidized/netbox.token` so a new device is monitored without another manual step. Replace it with a read-only token when you can (`scripts/set-secret.sh prometheus/netbox.token`). On a new install the setup service runs `scripts/seed-netbox.sh` (tenant, region, device roles, tag `ie-scan`). The `netbox-device-types` service then loads the vendored Cisco, Fortinet, and Palo Alto library (`docs/device-types.md`). NetBox is at **`https://<PUBLIC_HOST>:8444`** (`PORT_NETBOX`). Settings (edit configs, discovery) are `docs/settings-api.md`. Adding a device or an `ie-scan` prefix is `docs/testing-discovery.md`. An existing server whose Postgres data sits in an anonymous volume needs `docs/upgrade.md` before `up`.

States: `unconfigured → applying → complete | failed` (details and API: `docs/setup-api.md`). Optional parts: set `COMPOSE_PROFILES` in `.env`
(`logs,backup,traps`, …) and run `docker compose up -d` — **TODO: choosing profiles on the first-run page is not implemented**.

### 2.3 Where the client name lives, and renaming

* Single store: `data/setup/config.json` (persistent, in the project folder). The setup service copies it to `CLIENT_NAME`/`CLIENT_SLUG` in `.env`; those two variables drive
  everything else. Nothing client-specific is hard-coded. Do not hand-edit them in `.env`.
* Fixed compose project name `insightengine`: named volumes (`insightengine_<volume>`) keep their data when the client is renamed. The setup service and the socket proxy
  have no client suffix and are not recreated.
* **Renaming** (Settings → Client name → `POST /setup/client` with `confirm_downtime=true`) = re-render + recreate every other container. **Downtime: several minutes
  (estimate; measure on your host)** — all monitoring stops meanwhile. Side effects: new Prometheus series get the new `client` label while old series keep the old one;
  the NetBox Tenant/Region is not renamed automatically (TODO).
* InsightEngine is one client per server.

## 4. What was fixed (defect by defect)

| # | Defect in the pasted file | Fix |
|---|---|---|
| 1 | snmp-exporter `command` had a tab and a missing quote | Rewritten as a YAML list (`command:` items); validated with `docker compose config`. |
| 2 | Leading space before `http://` in healthcheck URLs | Removed everywhere; all exporters use `/-/healthy`. |
| 3 | `netbox-worker` media mount `/opt/arg/netbox/netbox/media` vs `/opt/netbox/netbox/media` | NetBox and workers share one named volume `netbox-media` at the same path (`/opt/netbox/netbox/media`). Old path only matters for migration. |
| 4 | Duplicate `N8N_DATA_TABLES_MAX_SIZE_BYTES` | n8n removed entirely (replaced by Activepieces). |
| 5 | Grafana mounted `/opt/arg/n8n` | Mount removed. |
| 6 | cust-exporter heading said "N8N WITH DEPENDENCIES" | Heading corrected; service is the custom exporter (profile `cust-exporter`). |
| 7 | Floating NetBox tag `netbox-4` | Pinned in `.env.example` (`NETBOX_IMAGE`). **TODO: confirm the version and use your own image that contains your plugin** (see §11). No digests are invented. |

Also: `insecure_skip_verify` replaced by a CA file; the `vasa_switches_shard_1.json` file_sd dependency is kept only as a
commented option; ports are `${PORT_*}` variables; all credentials come from `.env`/secret files.

## 5. Services and databases

* **One PostgreSQL container per app**, each with its own database and login: `netbox-postgres`, `activepieces-postgres`,
  `netdisco-postgres`, `insightengine-postgres`. Plus a Redis for NetBox (queue), NetBox (cache) and Activepieces.
* **Activepieces replaces n8n** (self-hosted, own Postgres + Redis; env names follow the official compose: `AP_*` in `.env` map to
  `AP_POSTGRES_*`, `AP_REDIS_*`, `AP_ENCRYPTION_KEY`, `AP_JWT_SECRET`, `AP_EXECUTION_MODE`, …). Behind Caddy on `PORT_ACTIVEPIECES`.
  **n8n workflows/credentials are not migrated** (different engine); rebuild them as flows.
* Core: Caddy (TLS, auth) · Prometheus · 2 SNMP exporters + 2 blackbox exporters behind `scrape-lb` (profile `scale` adds more) ·
  Alertmanager → `alert-relay` (placeholder webhook relay) · Grafana · Telegraf (API collector, host metrics) · NetBox (+ workers) · Activepieces · Netdisco · **setup service + docker-socket-proxy** (first run, §2) · customer UI (`insightengine-ui`, built from `ui/`).
* Profiles: `logs` (Loki 2160h = 90 days + Telegraf syslog; Promtail was not used because it reached EOL on 2026-03-02),
  `backup` (Oxidized with its device list from NetBox, git-backed, 3 months, config-change alerts), `traps` (snmptrapd),
  `tools` (snmp-generator, one-shot), `cust-exporter`.

## 6. Sizing for 20,000 devices — ALL NUMBERS ARE ESTIMATES

Assumptions behind the estimates (not measured): ~20,000 devices, an average ~150 active series per device after the
`sample_limit` caps (~3 M series), 60 s default interval (15–30 s for infrastructure, 120–300 s for the large WLC jobs).
Re-measure after the first week with `prometheus_tsdb_head_series` and container stats, then adjust `.env`.

| Component | Default limit (ESTIMATE) | Notes |
|---|---|---|
| Prometheus | 8 CPU / 24 GB (8 GB reserved) | ~3 M series × ~4 KB head ≈ 12 GB + query headroom. Retention 30 d (`PROM_RETENTION_TIME`), WAL compression on, query limits (`PROM_QUERY_*`). Disk ≈ 150–250 GB for 30 d — estimate; set `PROM_RETENTION_SIZE` to cap. |
| SNMP exporters | 2 × (2 CPU / 2 GB), `scale` adds 2 more | Load-balanced by target (`uri_hash`) so one device always hits one exporter. |
| Blackbox exporters | 2 (3 with `scale`) × (2 CPU / 1 GB) | ICMP per device. |
| Telegraf API | 2 CPU / 2 GB | Firewalls, controllers, NAC, SD-WAN APIs. |
| Telegraf host | 1 CPU / 512 MB | Host + docker metrics. |
| NetBox | 4 CPU / 4 GB + 3 workers × (1 CPU / 1 GB) | `NETBOX_WORKER_REPLICAS`. |
| NetBox PostgreSQL | 4 CPU / 8 GB | `shared_buffers=2GB`, `effective_cache_size=6GB`, `max_connections=200` (tunable in `.env`). |
| NetBox Redis / cache | 1 GB / 1.5 GB limit (1 GB maxmemory) | |
| Activepieces | app 2 CPU/2 GB, 3 workers × 2 CPU/2 GB, Postgres 2 GB, Redis 1 GB | Execution data retention 30 d. |
| Netdisco | backend 4 CPU/4 GB, web 1 GB, Postgres 4 GB | |
| Grafana | 2 CPU / 4 GB | |
| Alertmanager / Caddy / scrape-lb | 1 GB / 512 MB / 512 MB | |
| Loki (`logs`) | 4 CPU / 8 GB, 2160 h retention | Disk depends on syslog volume — unknown, measure. |
| Oxidized (`backup`) | 4 CPU / 4 GB, 60 threads, 4 h interval | 3 months of history kept (pruned daily). |
| **Host total (all profiles)** | **roughly 24 CPU / 80–90 GB RAM, 1 TB disk** | Estimate only; the core profile alone is lower. |

## 7. Prometheus targets from NetBox (`http_sd`)

Your pattern is kept: Prometheus calls the plugin list endpoint through Caddy
(`https://caddy:8443/api/plugins/lists/prometheus-devices/?status=active&role=<role>`) with `Authorization: Bearer` read from a
**token file** (`credentials_file`), and verifies TLS with the CA mounted at `/etc/ie-certs/ca.crt` (`ca_file`; the host file is `certs/ca.crt`, outside the read-only `/etc/prometheus` directory, `server_name: caddy`).
**This endpoint is "as used in your current stack"** — I did not verify or invent any plugin details, and the label names
`__meta_netbox_*` used in relabelling are my assumption of that plugin's output. Compare with `curl` output from your real plugin.
Roles are one job each (`icmp-*` and `snmp-*`) so each class gets its own interval, timeout and `sample_limit`.

## 8. Moving from the old stack (keeping data)

### 8.1 Rules
* The old stack is **read, never stopped, changed or deleted** by any script here. Only containers of the NEW stack are stopped/started.
* Old DB passwords are given as **file paths** (never typed into the page or sent over the API); `migrate.sh` reads the file and hands the password to the old container on **stdin**.
  Nothing is logged.
* Old Alertmanager/Caddy/Grafana-provisioning files are copied to `migration/imported/<timestamp>/` for **review**, not applied.
* New and old stacks can run **side by side** (`install.sh` probes each published host port and picks a free one).
* The old stack's folders are mounted **read-only** into the setup container under `SETUP_OLD_STACK_ROOT` (default `/opt`; change it in `.env` if the old stack lives elsewhere, then
  `docker compose up -d setup`). Paths outside it are rejected.

### 8.2 Steps (first-run page, or Settings → "Move from old stack")
1. Choose **Move from the old stack** and enter the old stack's paths (suggested defaults are `/opt/arg/...` and `/opt/netdisco/...` — **TODO: confirm**): compose file, NetBox/Netdisco
   Postgres container names, DB names/users, **password file paths**, NetBox media, Grafana data/provisioning, Alertmanager config, Caddyfile.
2. **Preflight** (`scripts/migrate.sh preflight`, read-only): old containers/images, versions, DB sizes, folder sizes, free disk, port conflicts. Errors block the next step.
3. **Confirm** and **Run** (`scripts/migrate.sh run`): starts only the new databases → stops only the new NetBox/Netdisco/Grafana → streams `pg_dump -Fc` from the old container
   into `pg_restore --clean --if-exists --no-owner --no-acl` in the new one (NetBox, Netdisco) → copies NetBox media and `grafana.db` → copies old Alertmanager/Caddyfile/provisioning for review.
   The page shows progress (`data/migration/progress.json`) and the log; `run` is refused unless the last preflight passed and the settings are unchanged.
4. **Prometheus history**: keep or start fresh (§8.4).
5. Log in, check NetBox data. **Recreate NetBox API tokens** (token values are not reusable across a restore): create a read-only token, then
   `scripts/set-secret.sh prometheus/netbox.token` (also `oxidized/netbox.token`, `cust-exporter/netbox.token`).
6. Merge the old Alertmanager routes/rules from `migration/imported/...` into `config/` by hand.
7. Cut over by changing ports in `.env` (or DNS); stop the old stack **yourself** when you choose to.

**CLI fallback (no web page):** copy `migration/migrate.conf.example` to `migration/migrate.conf` (mode 600), edit, then `scripts/migrate.sh preflight` and `scripts/migrate.sh run`.

Limits: a NetBox restore works to the **same or a newer** NetBox version only (the new one migrates the schema on first start);
restoring into an older PostgreSQL major is not supported. The scripts have **not been run against a real old stack**.

### 8.3 Rollback
Nothing in the old stack was changed, so rollback = keep using it. To drop the new stack: `docker compose down` (**without `-v`**
unless you want its data gone), restore the old ports if you moved them, done. Dumps kept with `KEEP_DUMPS=yes` live in `data/migration/dumps`.

### 8.4 Prometheus history — separate and optional
Separate and optional: the last step of the first-run page, and later Settings (**"Keep history / Start fresh"**; `POST /setup/prom-history`):

* **Start fresh**: do nothing.
* **Keep history** — `scripts/prom-history.sh`:
  * `check DATA_DIR` read-only block count/size.
  * `import --from-snapshot <old-prometheus-url> <old-data-dir>` asks the old Prometheus for a snapshot (`POST /api/v1/admin/tsdb/snapshot`;
    needs `--web.enable-admin-api` there; creates hard links under `snapshots/` in the old data dir — it modifies nothing else, and the
    snapshot is left for you to remove).
  * `import --from-dir <old-data-dir>` copies only complete blocks (ULID dirs), not `wal`/`chunks_head`, so the last ~2 hours are lost.
  * Only the NEW Prometheus is stopped during the copy (short gap in new graphs); blocks older than `PROM_RETENTION_TIME` are removed by Prometheus afterwards.

### 8.5 Settings page → "Move from old stack"
The customer UI in `ui/` calls the same setup-service endpoints as the first-run page (`docs/setup-api.md` §5): preflight → confirm → run →
history, one job at a time, paths only (no passwords), rollback note (§8.3).

## 9. Validation performed (honest statement)

`scripts/validate.sh` (static, starts nothing). In the preparation environment all of these **passed**:
`docker compose config` (standalone compose v5.6.1, **all profiles**, with dummy values and with an `install.sh`-generated `.env`), a compose policy check (only `docker-socket-proxy`
and `telegraf-host` mount the Docker socket, `setup`/proxy/UI publish no ports, the proxy network is `internal`, the proxy's dangerous API families stay `0`),
`promtool check config`, `amtool check-config`, Caddy adaptation of the main `Caddyfile` (incl. `forward_auth`; it only complains about certificate files that exist inside the container) and
`caddy validate` of the scrape-lb file, `blackbox_exporter --config.check`, `snmp_exporter --dry-run`, `loki -verify-config`, Telegraf 1.40.2 config parsing, `shellcheck`
(`install.sh`, `scripts/*.sh`, Oxidized and trapd scripts), `py_compile` + `node --check` for the setup service and page, **10 setup-API tests against a stub `docker` and stub scripts**
(client → apply → mode → migrate preflight/run → history, auth, lockout, edge lockdown, restart recovery), and a forbidden-word scan. `install.sh` was run non-interactively in a scratch copy
(`--no-start`, port-busy auto-detection checked); `migrate.sh preflight` against a stub `docker`; `prom-history.sh check` against a fake TSDB; the Oxidized and trap hooks against stubs.

**Not validated (could not be):** no Docker daemon was available, so **no container was started or built**, no healthcheck ran, no image tag was pulled/verified. In particular **untested**:
the socket-proxy allow-list against real `docker compose up`, the setup container running `docker compose` through the proxy with the same-path mount and `--no-build`, Caddy `forward_auth` at runtime,
the first-run page in a browser, `migrate.sh run` and `prom-history.sh import` against real stacks, the MIB generator, the vendor-API Telegraf examples,
and **anything on real devices or at 20,000-device scale.**

UI import checks on this change (Node.js 22.23.4, npm 10.9.9, shellcheck 0.9.0, PyYAML 6.0.1; Docker not installed):

* `npm ci`, `npm run build`, and `npm test` in `ui/` passed (4 files, 16 tests). `next build` wrote `ui/.next/standalone/server.js`. The production bundle omits the mock demo passwords. The image Dockerfile sets `NEXT_PUBLIC_IE_API_MODE=live`; an unset production build resolves to live as well.
* `docker-compose.yml` parses with PyYAML. `insightengine-ui` builds `./ui` (`Dockerfile`), listens via `PORT` / `IE_UI_PORT` (8080), and checks `GET /healthz`.
* `shellcheck` on `install.sh` and `scripts/validate.sh` passed. The full `shellcheck` run inside `scripts/validate.sh` still reports an existing info-level SC2015 in `scripts/prom-history.sh` line 57, so that script exits 1 with shellcheck 0.9.0. That line is unchanged here.
* The UI container image was not built and the stack was not started.

Later static checks (still no Docker daemon in this environment): `scripts/check-docker-copy.py` (COPY sources, including the named `netbox_config` context), `scripts/check-compose-audit.py` (read-only nested mounts, Prometheus-only `--web.enable-lifecycle`, Netdisco `required: false`, `http://127.0.0.1` healthchecks, Caddy `default_sni`), and `scripts/smoke.sh --self-test`. `scripts/smoke.sh` without that flag waits on a running project and does not start it. `install.sh --no-start` was re-run in a scratch copy to confirm resume does not rewrite `.env`. A fake `iptables -t nat -S` with a `KUBE-SERVICES` loadbalancer rule for the chosen host moved ports 80 and 443 and printed why; a rule for a different address did not. Caddy 2.11.2, with the certificate for `203.0.113.10`, accepted `openssl s_client` without `-servername` on the setup, NetBox, Grafana, and Prometheus ports (the socket's local address was `127.0.0.1`, which is the container case). The same handshake without `default_sni` returned `tlsv1 alert internal error`. No container was built or started, so `python manage.py check` inside the NetBox image was not run; the lists plugin was compared with the NetBox v4.6.3 source instead.

## 10. Security notes and flags

* **Setup service = root-equivalent (flag).** It drives Docker through `docker-socket-proxy` on an internal-only network; the web page and any UI backend never get a raw socket.
  The proxy filters by API family, **not** by project, so a holder of the setup token could still create a container that mounts `/`. Mitigations: token (file `secrets/setup/token`,
  rotate by replacing the file + `docker compose restart setup`), no published port, fixed list of actions (no arbitrary command), lockout after 10 bad tokens/min, 64 KB body limit,
  Caddy lockdown after setup (`/setup/*` is `404` at the edge once `complete`, unless `SETUP_PUBLIC_AFTER_COMPLETE=yes`). The project folder is mounted **read-write** and the old-stack root
  **read-only** in the setup container. You can switch it off after setup: `docker compose stop setup docker-socket-proxy` (Settings rename/move then needs them started again).
* **Token handling:** the page takes the token from the operator and keeps it in memory only; no secret is embedded in the page, API responses or logs.
* **Plain HTTP between Caddy and `setup`** stays on the internal `monitoring-net`.
* SELinux hosts: the proxy may need `privileged: true` (TODO, see compose comment).
* `telegraf-host` mounts the Docker socket and host root read-only for metrics. This is root-equivalent: **TODO(Phindani)**: consider
  `node_exporter` plus a docker-socket-proxy (read-only API) instead, or drop the docker input.
* Activepieces `AP_EXECUTION_MODE=UNSANDBOXED` is the default here; sandboxing needs extra privileges. Decide before running untrusted flows.
* Back up `AP_ENCRYPTION_KEY` (lost key = stored connections unreadable) and `NETBOX_SECRET_KEY`.
* `ca.key` stays in `certs/`; move it offline after installation if you can.

## 11. Assumptions and TODOs needing Phindani's input

1. **NetBox image/version**: pinned stock tag `netboxcommunity/netbox:v4.7.3` as a placeholder. Use **your** image with the Prometheus `lists` plugin and the exact version you run (and decide whether the plugin name `lists` is right).
2. **All image tags** in `.env.example` were the latest releases found while preparing this bundle; confirm them. Netdisco is pinned to `netdisco/netdisco:2.116000` (compose appends `-postgresql`, `-backend`, and `-web`). Oxidized is still on `latest` (TODO: pin).
3. **Plugin endpoint and `__meta_netbox_*` label names** (§7) are unverified.
4. **MIB set / SNMP modules**: `snmp/generator.yml` is untested; `snmp/out/snmp.yml` is a skeleton with `if_mib` and `system` modules. Provide the vendor MIB list (Cisco, Fortinet, Palo Alto, Aruba, Juniper, …) and run `docker compose --profile tools run --rm snmp-generator`.
5. **API credential names** for Telegraf (`secrets/telegraf/*`): FortiGate, PAN-OS, ISE, DNA Center, SD-WAN. The `*.conf.example` files use placeholder endpoints that must be confirmed against each vendor's current API.
6. **Container UIDs**: Telegraf 10001, trapd 10002, Prometheus 65534, Oxidized 30000 — confirm for your images.
7. **Netdisco**: image tag `2.116000`, PostgreSQL 18. The data volume is `netdisco-pgdata` mounted at `/var/lib/postgresql` (PGDATA is `/var/lib/postgresql/18/docker`). The entrypoint sets a random superuser password; the app role and database come from `NETDISCO_DB_USER` / `NETDISCO_DB_PASS` / `NETDISCO_DB_NAME`. `netdisco-db-init` finishes before web and backend. Port `5000` (`PORT_NETDISCO`). SNMP-only `deployment.yml` is rendered into `nd-site-local` (`deployment.yml.example`).
8. **Oxidized**: model/platform mapping uses NetBox `platform.slug`; the image must contain `curl` for the hooks (otherwise build a small derived image).
9. **Old stack names/paths** (`/opt/arg/...`, `/opt/netdisco/...`, container names) are installer defaults you can edit.
10. **Alert rules** in `config/prometheus/alert-rules.yml` are 4 skeletons; replace with your real rules. `alert-relay` is a placeholder: `config/alert-relay/destinations.json` ships with one disabled example; the UI is meant to write the real file later. Destination URLs may contain secrets, so do not commit the real file.
11. **Sizing**: every number is an estimate; measure and adjust.
12. `scripts/seed-netbox.sh` uses NetBox 4.x API paths. NetBox 4.6 v2 tokens are `Bearer nbt_<key>.<secret>` (v1 `Token` is deprecated). The scripts pick the scheme from the token prefix.
13. n8n data is **not** migrated to Activepieces.
14. `vasa_switches_shard_1.json` file_sd is not used; uncomment the commented job if you still need it.
15. **Customer UI** is `ui/` (Next.js). Empty `IE_UI_IMAGE` builds `insightengine-ui:local` from `ui/Dockerfile` (`npm ci`, port 8080, `NEXT_PUBLIC_IE_API_MODE=live`). `IE_UI_PORT` defaults to 8080. `ui/Dockerfile.placeholder` runs only when `ui/Dockerfile` is absent. Three files under `ui/public/` are generated placeholders to replace with the originals from the UI source repo: `public/assets/images/app_logo.png`, `public/assets/images/no_image.png`, `public/favicon.ico`. The `tecnativa/docker-socket-proxy:v0.5.0` tag is still **unverified**. The UI image was not built here (no Docker daemon).
16. **Profiles** (`logs`, `backup`, `traps`, …) cannot yet be chosen on the first-run page; set `COMPOSE_PROFILES` in `.env`.
17. **NetBox Tenant rename** on client rename, and automatic `seed-netbox.sh` after setup: not implemented.
18. **Old stack location** defaults (`/opt`) and names are assumptions; confirm `SETUP_OLD_STACK_ROOT`.
