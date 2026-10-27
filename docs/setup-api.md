# Setup service HTTP API

Source of truth for the UI developer. Implemented in `setup/server.py` (Python standard library only), tested with
`setup/tests/test_setup_api.py` against a **stub** `docker` and stub scripts (no real Docker daemon was available).
All sizing/time numbers in this document are **estimates**; nothing was tested on real devices.

* Container `ie-setup`, listens on port `8099` **inside** the compose networks. **No published port.**
* Reached by browsers only through Caddy: `https://<PUBLIC_HOST>[:PORT_HTTPS]/setup/...`
* Everything is JSON (`Content-Type: application/json`) except the three static page files.
* The service runs a **fixed set of actions**. There is no endpoint that runs an arbitrary command or reads an arbitrary file.

## 1. Authentication

* A random token is created by `install.sh` in the file `secrets/setup/token` (mode 0400/0600, no trailing newline). It is mounted into
  the container as `/run/secrets/setup_token`. `install.sh` prints only the file path, never the value.
* Send it on every call except the ones marked *public*: `Authorization: Bearer <token>`
* The token is **never** returned, logged or embedded in the page. The first-run page keeps what the operator types in memory only.
* Wrong/missing token → `401 {"error": "missing or invalid token"}`. 10 failures per minute per client address → `429` for the rest of that minute.
  (Behind Caddy the client address comes from `X-Forwarded-For`, which Caddy sets.)
* To rotate: write a new value to `secrets/setup/token` and `docker compose restart setup`.

Errors always look like `{"error": "<human readable message>"}` with one of: `400` bad input, `401`, `404`, `409` wrong state / another
action running, `413` body over 64 KB, `429`, `500`.

## 2. State machine

`GET /setup/state` returns `state` and `step`.

| `state` | meaning |
|---|---|
| `unconfigured` | first run, in progress. `step` = `client` → `admin` → `mode` → (`migrate` → `history`, only for "move") |
| `applying` | the client name is being rendered and containers are being (re)created (background job) |
| `complete` | setup finished; Caddy sends `/` to the custom UI |
| `failed` | the last apply failed (`error` says why). Call `POST /setup/client` again to retry |

```
unconfigured/client --POST client--> applying --ok--> unconfigured/admin --POST admin--> unconfigured/mode --POST mode(new)--> complete
                                                                                              \--POST mode(move)--> unconfigured/migrate
                                         \--error--> failed        preflight -> run (ok) -> unconfigured/history
                                                                   POST prom-history (keep ok | fresh) --> complete
```

After `complete`, `POST /setup/client` (rename) re-applies and returns to `complete` (§4.2); the migrate/history calls remain available (§5).

Only one background job runs at a time (`job.kind` = `apply | preflight | migrate | prom-history`); starting another gives `409`.
Job state survives restarts in `data/setup/job.json`; a job that was running when the service restarted is reported as `failed` ("interrupted").

## 3. Public / gate endpoints (no token)

| Method + path | Purpose |
|---|---|
| `GET /setup/` | the plain-HTML first-run page (`/setup/app.js`, `/setup/style.css` are its assets). CSP: scripts only from the same origin. |
| `GET /setup/healthz` | `200 {"ok": true}` (compose healthcheck) |
| `GET /setup/gate` | used only by Caddy `forward_auth`: `200` if `state == complete`, otherwise `302 Location: /setup/` |
| `GET /setup/state` **without** `Authorization` | minimal: `{"state": "unconfigured", "step": "client"}` — used by the custom UI to decide whether to redirect |

### UI contract (custom UI)
1. On load call `GET /setup/state` (same origin, no token). If `state != "complete"`, `location.replace("/setup/")`.
2. Caddy already enforces this server-side (`forward_auth` → `/setup/gate`); if the setup service is down Caddy fails **closed** (no UI).
3. Settings → Client name and Settings → "Move from old stack" call the endpoints below with the token. The custom **backend** may hold the token as a
   secret mount (`setup_token`); it never needs, and must never get, the Docker socket.

### Edge lockdown after setup
Requests that come through Caddy carry `X-Setup-Edge: 1`. Once `state == complete`, through the edge **only** `/setup/state`, `/setup/gate` and
`/setup/healthz` answer; everything else is `404`, unless `SETUP_PUBLIC_AFTER_COMPLETE=yes` in `.env`. Internal callers on `monitoring-net`
(for example the custom backend calling `http://setup:8099/setup/...`) are not affected.

## 4. Endpoints

Base URL from the browser: `https://<PUBLIC_HOST>/setup`. Internal: `http://setup:8099/setup`.

### 4.1 `GET /setup/state`
With token (full):
```json
{
  "state": "unconfigured", "step": "mode",
  "client_name": "Acme Bank & Co.", "client_slug": "acme-bank-co",
  "mode": null, "history": null, "migrated": false, "error": null,
  "updated_at": "2026-10-24T15:40:12Z",
  "job": {"id": "a1b2c3d4e5f6", "kind": "apply", "state": "succeeded", "started": "2026-10-24T15:38:01Z",
          "finished": "2026-10-24T15:40:11Z", "exit_code": 0, "error": null},
  "last_preflight": null
}
```
Before a name is chosen `client_name` and `client_slug` are `"unconfigured"`. `job.state`: `running | succeeded | failed`.

### 4.2 `POST /setup/client` — choose / rename the client (token)
```json
{"client_name": "Acme Bank & Co."}
```
`202`:
```json
{"state": "applying", "job_id": "a1b2c3d4e5f6", "client_name": "Acme Bank & Co.", "client_slug": "acme-bank-co"}
```
* Name rules: 1–60 characters; no quotes, backtick, `$`, backslash or control characters; must contain a letter or digit; the slug (lower-case,
  `a-z0-9-`, max 40) may not be `unconfigured`. Otherwise `400`.
* What the job does (fixed steps): (1) write `CLIENT_NAME`/`CLIENT_SLUG` into `.env` from the config store (§6), (2) `docker compose config --services`,
  (3) `docker compose up -d --no-build <every service except setup and docker-socket-proxy>` for this project only (project name is fixed:
  `insightengine`), so containers whose name/labels/env contain the client are **recreated**. Progress: poll `GET /setup/state` (`state`, `job`) and `GET /setup/log`.
* When the job succeeds: first run → `state=unconfigured, step=admin`; rename after `complete` → back to `complete`. On error → `state=failed`.

### 4.2a `POST /setup/admin` (token)

```json
{"email": "admin@example.com", "password": "at least 12 characters, a letter and a digit"}
```

or `{"email": "admin@example.com", "generate": true}`.

Allowed only at `step=admin` (after the client name is applied, before new-vs-move). The setup service calls ie-config `POST /internal/bootstrap-admin` with the setup bearer token. The password is not written to `setup.log`. `200` is `{"state":"unconfigured","step":"mode"}`. When `generate` is true and ie-config accepted the user, the response also has `generated_password` (once). If an administrator already exists, ie-config returns 409 and setup still advances to `mode` without a generated password. A failure to reach ie-config is `502`.

Rename (still `POST /setup/client`):
* **Rename after `complete`** needs `"confirm_downtime": true` in the body, otherwise `409` ("renaming recreates all containers ..."). Same name again = no confirm needed.
  **Downtime (estimate): several minutes** — all monitoring containers are stopped and recreated (typically 2–10 min depending on the host; measure it).
  Data is kept: the compose project name is fixed so named volumes (`insightengine_<volume>`) are reused. Side effects: the Prometheus `client`/`client_name`
  labels change from that moment, so new series carry the new label and old series keep the old one; the NetBox Tenant/Region created by `seed-netbox.sh`
  is **not** renamed (TODO). The setup service and the socket proxy are not recreated.

### 4.3 `POST /setup/mode` (token)
```json
{"mode": "new"}        // or "move"
```
`200`: `{"state": "complete", "step": "done"}` for `new`; `{"state": "unconfigured", "step": "migrate"}` for `move`.
`409` unless `step` is `mode` (the administrator step comes first). `409` if the client name has not been applied yet.

### 4.4 `POST /setup/migrate/preflight` (token) — read-only check of the old stack
Allowed in `step=migrate|history` of the move flow, or when `state=complete` (Settings).
```json
{
  "old_stack": {
    "compose_file": "/opt/arg/docker-compose.yml",
    "netbox_pg_container": "netbox-postgres",
    "netbox_db": "netbox",
    "netbox_db_user": "netbox",
    "netbox_db_password_file": "/opt/arg/secrets/netbox_db_password",
    "netdisco_pg_container": "netdisco-postgres",
    "netdisco_db": "netdisco",
    "netdisco_db_user": "netdisco",
    "netdisco_db_password_file": "/opt/netdisco/secrets/db_password",
    "netbox_media_path": "/opt/arg/netbox/media",
    "grafana_data_path": "/opt/arg/grafana",
    "grafana_provisioning_path": "/opt/arg/grafana/provisioning",
    "alertmanager_config_path": "/opt/arg/alertmanager/alertmanager.yml",
    "caddyfile_path": "/opt/arg/caddy/Caddyfile",
    "keep_dumps": true
  }
}
```
Fields: `compose_file`, `stack_dir`, `netbox_container`, `netbox_pg_container` (**required**), `netbox_db`, `netbox_db_user`,
`netbox_db_password_file` (**required**), `netdisco_pg_container`, `netdisco_db`, `netdisco_db_user`, `netdisco_db_password_file`, `netbox_media_path`,
`grafana_data_path`, `grafana_provisioning_path`, `grafana_container`, `alertmanager_config_path`, `caddyfile_path`, `prom_container`, `keep_dumps` (bool).
Unknown fields → `400`. **No password value is ever accepted**: `*_password_file` is a path. Paths must be absolute, contain no `..`, lie under
`SETUP_OLD_STACK_ROOT` (default `/opt`, mounted read-only in the container) and not inside this project. Container/db names are validated.

`202`: `{"job_id": "f00d...", "preflight_id": "f00d..."}` (the preflight id is the job id).
Then poll `GET /setup/migrate/status`. The result is `last_preflight` = `{"id", "passed", "errors", "warnings", "time", "conf_sha256"}`;
the readable report (old containers/images, versions, DB sizes, folder sizes, free disk, port conflicts) is in `log_tail` and in the log file named by `preflight_log`.

### 4.5 `POST /setup/migrate/run` (token) — copy the data (old stack only read)
```json
{"confirm": true, "preflight_id": "f00d..."}
```
`202`: `{"job_id": "1234..."}`. Refused (`400/409`) unless `confirm` is `true`, the **last** preflight passed, `preflight_id` matches it, and the
settings did not change since (checksum). Exactly one migration job at a time. On success the move flow advances to `step=history`.
The old stack is never stopped, changed or deleted (`scripts/migrate.sh`). Rollback: keep using the old stack (README §8.3).

### 4.6 `GET /setup/migrate/status` (token)
```json
{
  "job": {"id": "1234...", "kind": "migrate", "state": "running", "started": "2026-10-24T15:50:00Z", "finished": null, "exit_code": null, "error": null},
  "preflight": {"id": "f00d...", "passed": true, "errors": 0, "warnings": 2, "time": "2026-10-24T15:45:10Z", "conf_sha256": "..."},
  "preflight_log": "data/migration/migrate-20261024-154510.log",
  "progress": [
    {"time": "2026-10-24T15:50:03Z", "step": "netbox-db", "state": "running", "detail": "restoring"}
  ],
  "log_tail": ["2026-10-24T15:50:03Z $ /opt/insightengine/scripts/migrate.sh run", "..."]
}
```
`progress` = the last 100 JSON lines of `data/migration/progress.json` as written by `migrate.sh` (keys: `time`, `step`, `state`, `detail`; the step names are defined by that script).
`log_tail` = the last 40 lines of the setup log.

### 4.7 `POST /setup/prom-history` (token) — keep or drop old Prometheus history
Start fresh (does nothing to data):
```json
{"mode": "fresh"}
```
`200` `{"state": "complete", "step": "done"}`.

Keep, from a snapshot of the old Prometheus (needs `--web.enable-admin-api` there; the old Prometheus must be reachable from the setup container —
`host.docker.internal` is mapped to the host):
```json
{"mode": "keep", "method": "snapshot", "old_url": "http://host.docker.internal:9090", "old_data_dir": "/opt/arg/prometheus/data"}
```
Keep, copying complete blocks from the old data directory:
```json
{"mode": "keep", "method": "dir", "old_data_dir": "/opt/arg/prometheus/data"}
```
`202`: `{"job_id": "..."}` (poll `GET /setup/migrate/status`). During the copy only the NEW Prometheus is stopped (short gap in new graphs). The last ~2 hours are
lost with `dir`. Allowed in `step=history` or when `state=complete`. `old_url` must be `http(s)://host[:port][/path]`; `old_data_dir` is validated like the migrate paths.

### 4.8 `GET /setup/log?lines=200` (token)
`lines` 1–1000 (default 200).
```json
{"lines": ["2026-10-24T15:38:01Z render: .env <- client 'Acme Bank & Co.' (acme-bank-co)", "2026-10-24T15:38:01Z $ docker compose ..."], "size": 18432}
```
The log (`data/setup/setup.log`) contains commands and their output. It never contains the token; scripts are written not to print secrets.

## 5. Settings page → "Move from old stack" (after setup is complete)

Same calls, same token; the state stays `complete`:

| UI element | Call |
|---|---|
| Settings → Client name → "Rename" (shows the downtime warning) | `POST /setup/client {"client_name": "...", "confirm_downtime": true}` then poll `GET /setup/state` |
| "Move from old stack" → fields for the old paths → "Check" | `POST /setup/migrate/preflight {"old_stack": {...}}` → poll `GET /setup/migrate/status` |
| Report + checkbox "I understand the old stack is only read; data is copied" → "Run" | `POST /setup/migrate/run {"confirm": true, "preflight_id": "..."}` → poll `GET /setup/migrate/status` |
| "Keep history / Start fresh" | `POST /setup/prom-history {...}` |
| "Show log" | `GET /setup/log?lines=500` |

Notes for the UI: show `409` messages as they are; show only one running job; the UI takes **paths** of password files, never passwords; after
a migration tell the user to recreate NetBox API tokens (`scripts/set-secret.sh`, README §8.2). Admin-only access to these screens is the custom UI's job
(role check) in addition to the token.

## 6. Config store

`data/setup/config.json` (mode 0600, inside the project directory, persists across restarts; written atomically):
```json
{"schema": 1, "state": "complete", "step": "done", "client_name": "Acme Bank & Co.", "client_slug": "acme-bank-co",
 "mode": "new", "history": "fresh", "migrated": false, "last_preflight": null, "error": null, "updated_at": "2026-10-24T15:41:00Z"}
```
It is the **single** place for the client identity. On every apply the service copies `client_name`/`client_slug` to `CLIENT_NAME`/`CLIENT_SLUG` in `.env`
(the only template step: every compose file, label and title reads those two variables). Do not edit `.env` by hand for the client name.

InsightEngine is one client per server.

## 7. Docker access and its risk

The setup service has **no** raw Docker socket. `DOCKER_HOST=tcp://docker-socket-proxy:2375` points to `ie-docker-proxy`
(Tecnativa docker-socket-proxy) on the **internal** network `docker-proxy-net` (no route outside). The proxy holds the socket and allows only the API families
`CONTAINERS, IMAGES, NETWORKS, VOLUMES, EXEC, INFO, EVENTS, PING, VERSION` plus `POST` (create/start/stop/restart/delete); `BUILD, COMMIT, AUTH, SECRETS, CONFIGS, SWARM,
SERVICES, TASKS, NODES, PLUGINS, SYSTEM, SESSION, GRPC, DISTRIBUTION` are blocked. `scripts/validate.sh` asserts this.

**This is still root-equivalent.** The proxy filters by endpoint family, not by project or label, so whoever holds the setup token (or breaks into the setup
container) can create a container that bind-mounts `/` and so act as root on the host. The setup container additionally has this project directory read-write
(same absolute path as on the host) and the old-stack root read-only. Mitigations: token auth, no published port, internal network only, fixed action list, no
shell-string execution, edge lockdown after setup, request body limit, brute-force lockout. To reduce the risk further you can stop the service after setup:
`docker compose stop setup docker-socket-proxy` (then Settings → rename/move is unavailable until you start them again), or remove them from the compose file.
