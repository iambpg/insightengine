# Settings API (`ie-config`)

Base path `/api/v1`. This is the contract the customer UI calls. Fields may be added. Existing fields keep their meaning.

Errors:

```json
{ "error": { "code": "forbidden", "message": "human text", "details": {} } }
```

`details` is omitted when empty. A failed save that does not validate returns **422** with that envelope **and** the validate fields (`ok`, `messages`, `tool`, `durationMs`) on the same object.

## Auth

Cookie `ie_session` (httpOnly, SameSite=Lax, Secure when `COOKIE_SECURE=1`). Every state-changing request except login sends header `X-CSRF-Token` with the token from login or `/auth/me`.

Roles: `Administrator`, `Engineer`, `Operator`, `Read-only`.

Operator and Read-only receive **403** `forbidden` on `/api/v1/settings/*` and `/api/v1/discovery/*`. Engineer may view every app and edit apps that are not sensitive. Administrator may edit sensitive apps and restart containers. Sensitive apps: caddy, netbox, trapd, activepieces, postgres, host.

| Method | Path | Body | Result |
|---|---|---|---|
| POST | `/api/v1/auth/login` | `{email, password}` | `{ok, role, csrfToken}` and the cookie. 401 `invalid_credentials`. 429 `locked` or `rate_limited`. |
| POST | `/api/v1/auth/logout` | | `{ok: true}` |
| GET | `/api/v1/auth/me` | | `{email, role, csrfToken}` |
| GET | `/api/v1/auth/users` | | Administrator. `[{email, role}]` |
| POST | `/api/v1/auth/users` | `{email, password, role}` | Administrator. Creates another user. |

Login: 5 failures lock the account for 15 minutes (the 5th failure is still 401; the next attempt is 429 `locked`). 30 failures per minute per IP return 429 `rate_limited`. Unknown emails get the same 401 text as a wrong password.

The first Administrator is **not** created here. The setup service calls `POST /internal/bootstrap-admin` (not under `/api/v1`, not routed by Caddy) with the setup bearer token. A second call returns 409 `already_bootstrapped`.

## Applications and files

`GET /api/v1/settings/apps` — list. Each app has `id`, `name`, `description`, `group`, `container` (`name`, `state`, optional `health`), `version`, `uiUrl`, `files`, `actions`.

File object: `id`, `path`, `label`, `language`, `sizeBytes`, `editable`, `hasSecrets`, and `readOnlyReason` when it is not editable. File ids are registry keys. They are never filesystem paths. `..` and slashes return 404.

`GET /api/v1/settings/overview` — `{apps: [{id, container, lastReload}]}`.

`GET /api/v1/settings/apps/{app}/files/{file}` — `{content, etag, modifiedAt, language, maskedKeys}`. Secret files return 403 `secret_file` and the bytes are not read. Secret-looking values inside an editable file are replaced with `"__SECRET__:<name>"` (quoted so the colon does not break YAML). `${ENV}` and `@@PLACEHOLDER@@` are left as-is. A repeated key becomes `password#2`.

`POST .../validate` `{content}` → `{ok, messages: [{severity, line?, column?, text}], tool, durationMs}`.

`POST .../diff` `{content}` → unified diff. Both sides are masked.

`PUT ...` `{content, etag, comment, apply}`:

- Missing etag: 400 `etag_required`. Etag `""` creates a missing file.
- Stale etag: 409 `etag_conflict`, `details.etag` is the current tag.
- Invalid: 422, **nothing is written**.
- Otherwise: backup, atomic write (temp file, fsync, rename), audit row. `apply: true` runs reload, or restart when the app has no reload.
- A leftover `__SECRET__:` placeholder that was not in the previous file: 422 `secret_placeholder`.
- Body limit 6 MB. Editable files 5 MB. Larger files stay read-only.

`GET .../history` — newest 50 that are also inside 90 days (an entry is kept when it is among the newest 50 **or** younger than 90 days).

`GET .../history/{id}` — masked content.

`POST .../history/{id}/restore` `{apply?}` — validates, then writes. 422 leaves the live file unchanged.

`POST /api/v1/settings/apps/{app}/actions/{action}` `{params?}` → `{ok, message, output?}`.

`GET /api/v1/settings/audit?app&user&from&to&page` — append-only. There is no delete.

`GET .../files/{file}/structured` — optional view (Prometheus jobs, Alertmanager routes, SNMP auth/module names). It does not save. The raw editor remains the way to save.

## App ids

`prometheus`, `alertmanager`, `snmp-exporter`, `snmp-generator`, `blackbox-exporter`, `telegraf`, `grafana`, `caddy`, `netbox`, `activepieces`, `loki`, `promtail-or-syslog` (syslog is Telegraf, not Promtail), `oxidized`, `trapd`, `netdisco`, `postgres` (read-only), `host` (read-only copies; ie-config does not apply them to the OS).

## SNMP generator

`POST /api/v1/settings/apps/snmp-generator/actions/generate` runs the generator and returns a candidate diff against the live `snmp.yml`. It does **not** replace the live file. Saving the candidate is a separate PUT on `snmp-exporter` / `snmp.yml` with `apply: true`.

MIBs: `GET` and `POST` (multipart field `file`) and `DELETE` `/api/v1/settings/apps/snmp-generator/mibs` and `.../mibs/{name}`. Names match `^[A-Za-z0-9][A-Za-z0-9_.-]{0,120}$` and end in `.mib`, `.txt`, `.my`, or `.smi`. 2 MB per file, 20 MB total.

## Discovery

| Method | Path | Who |
|---|---|---|
| GET | `/api/v1/discovery/unapproved` | Administrator, Engineer |
| POST | `/api/v1/discovery/{id}/approve` | same. Optional body `{name, site, role}` |
| POST | `/api/v1/discovery/{id}/reject` | same |

Approve creates the device in NetBox (manufacturer, type, role, site, a `/32` on interface `mgmt`, primary IPv4) and the Prometheus jobs pick it up on the next http_sd refresh.

Netdisco scan settings are the editable file `netdisco` / `sync.yml` (`prefix_selector` `tag` | `custom_field` | `all`, tag `ie-scan`, `interval_hours` default 6). Actions: `sync-prefixes`, `scan-now`, `refresh-unapproved`.

## Vault

Administrator only. An Engineer, Operator, or Read-only caller receives **403** `forbidden`. The list never contains a secret value. Responses send `Cache-Control: no-store`.

`GET /api/v1/settings/vault` — `{readOnly: true, revealSeconds: 300, groups: [{id, name, note, endpoints, entries}]}`.

Each group is one app: NetBox, Grafana, Prometheus / Alertmanager (Caddy basic auth), Activepieces, Netdisco, Oxidized, SNMP, UI / admin, and Other. `endpoints` is `{name, portKey, port, scheme, url}` taken from the `PORT_*` value in `.env` (the compose default when the key is missing). `url` is empty for UDP. Each entry is `{key, secret, set}` and, when `secret` is false, `value`. A secret entry has no `value`.

`POST /api/v1/settings/vault/unlock` `{password}` — checks the current administrator password and opens a reveal session for `expiresIn` seconds (300). **401** `invalid_credentials` when the password is wrong. The password is not logged or stored in the audit row. **429** `rate_limited` after repeated failures.

`POST /api/v1/settings/vault/reveal` `{key, action}` — `action` is `reveal` (default) or `copy`. Returns `{key, value, action}` for that one key. A secret key without a live reveal session is **403** `reauth_required` and the value is not returned. An unknown key is **404**. Each successful reveal or copy appends an audit row (`vault-reveal` or `vault-copy`) with the user, the key, and the time. The value is not written to the audit row or the process log.

There is no write route. `.env` is mounted read-only into ie-config.

## Health

`GET /healthz` (no `/api/v1` prefix, no cookie) returns `{ok: true}` for the container healthcheck.
