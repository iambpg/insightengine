# Importing this UI into the engine repo

This directory is `ui/` in `iambpg/insightengine`. One `git clone` of that repository plus `./install.sh` builds it. Leave `IE_UI_IMAGE` empty: the installer builds `insightengine-ui:local` from `Dockerfile` (`npm ci`, `NEXT_PUBLIC_IE_API_MODE=live`, port 8080, `GET /healthz`). Caddy sends `/api/v1/*` to `ie-config`, `/setup/*` to the setup service, and `/healthz` plus the rest of the site to this UI. Open `https://<PUBLIC_HOST>/` : the first-run page is `/setup/` until setup is complete, then this UI.

The app has its own `package.json`, `Dockerfile`, `.dockerignore`, and `next.config.mjs` (`output: 'standalone'`). It does not import paths outside itself, and it does not read secrets from the environment.

## Build

```bash
cd ui
npm ci
npm run build
```

The Dockerfile runs `npm ci` from the committed lockfile and sets `NEXT_PUBLIC_IE_API_MODE=live` before `npm run build`.

Container image (`./install.sh` tags this `insightengine-ui:local` when `IE_UI_IMAGE` is empty):

```bash
docker build -t insightengine-ui:local .
docker run --rm -p 8080:8080 -e PORT=8080 insightengine-ui:local
```

The process is `node server.js` from the standalone output. It binds `HOSTNAME` (default `0.0.0.0` in the image) and `PORT` (default `8080`). `GET /healthz` is the healthcheck.

`npm run dev:mock` is the local demo (port 4028) with mock data and demo accounts.

## Environment

| Variable                  | Values           | When                                                                                      |
| ------------------------- | ---------------- | ----------------------------------------------------------------------------------------- |
| `NEXT_PUBLIC_IE_API_MODE` | `live` or `mock` | Build time. The Docker build sets `live`. Unset production builds also resolve to `live`. |
| `PORT`                    | TCP port         | Runtime. Image default `8080`.                                                            |
| `HOSTNAME`                | Bind address     | Runtime. Image default `0.0.0.0`.                                                         |

No API keys, database URLs, or session secrets belong in this UI. The session is an httpOnly cookie set by `ie-config`. The browser stores the CSRF token from login only in `sessionStorage` and sends it as `X-CSRF-Token` on writes. The UI does not log request bodies, file contents, or tokens.

## Caddy

| Browser path            | Upstream      |
| ----------------------- | ------------- |
| `/api/v1/*`             | `ie-config`   |
| `/setup/*`              | setup service |
| `/healthz` and the rest | this UI       |

All `/api/v1` calls use `credentials: 'include'`.

### Setup service

- `GET /setup/state` → `{ "state": "unconfigured" \| "applying" \| "complete" \| "failed", "step"?: string }`
- The UI redirects to `/setup/` unless `state` is `complete`.
- A network error or a non-JSON response does **not** redirect, so a down setup service cannot loop the browser.
- Mock mode returns `complete` unless `sessionStorage['ie.mock.setupState']` or `globalThis.__IE_MOCK_SETUP__` is one of the four states.

### ie-config (this UI calls these)

Auth:

- `POST /api/v1/auth/login` `{ email, password }` → `{ ok, role, csrfToken }`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me` → `{ email, role, csrfToken }`

Settings (see `docs/settings-api.md` for the shared field list):

- `GET /api/v1/settings/apps`
- `GET /api/v1/settings/overview`
- `GET /api/v1/settings/audit?app=&user=&from=&to=&page=`
- `GET /api/v1/settings/apps/{app}/files/{file}`
- `POST /api/v1/settings/apps/{app}/files/{file}/validate` `{ content }`
- `POST /api/v1/settings/apps/{app}/files/{file}/diff` `{ content }`
- `PUT /api/v1/settings/apps/{app}/files/{file}` `{ content, etag, comment, apply }`
- `GET /api/v1/settings/apps/{app}/files/{file}/history`
- `GET /api/v1/settings/apps/{app}/files/{file}/history/{id}`
- `POST /api/v1/settings/apps/{app}/files/{file}/history/{id}/restore` `{ apply }`
- `POST /api/v1/settings/apps/{app}/actions/{action}` `{ params? }`
- `GET|POST /api/v1/settings/apps/snmp-generator/mibs`
- `DELETE /api/v1/settings/apps/snmp-generator/mibs/{name}`

Discovery:

- `GET /api/v1/discovery/unapproved`
- `POST /api/v1/discovery/{id}/approve` `{ role, site, name?, platform? }`
- `POST /api/v1/discovery/{id}/reject`
- `POST /api/v1/discovery/scan` `{ target: "prefix" \| "ip", value }`
- `GET /api/v1/discovery/scans`

Existing screens also call `/api/v1/summary`, `/api/v1/devices`, `/api/v1/sites`, and `/api/v1/alerts` with the query shapes noted in `src/lib/apiClient.ts`.

Errors stay `{ "error": { "code", "message", "details" } }`. `422` puts the validate payload in `details` and the editor keeps the draft. `409` means the etag is stale; the editor offers reload or a merge view.

## Shapes the contract describes in prose

These are what the UI parses. Change them in both PRs if they move.

`GET /api/v1/settings/overview`

```json
{
  "generatedAt": "ISO-8601",
  "apps": [
    {
      "id": "prometheus",
      "container": {
        "name": "prometheus-ntt",
        "state": "running",
        "health": "healthy",
        "uptimeSeconds": 1
      },
      "lastReloadAt": null,
      "lastError": null
    }
  ]
}
```

`GET /api/v1/settings/audit` → `{ "page": 1, "entries": [{ "id", "at", "user", "app", "file", "action", "comment", "result", "sourceIp" }] }`

`GET .../history/{id}` → `{ "id", "content", "savedAt", "user", "comment" }`. A raw text body is also accepted.

`POST .../actions/generate` on `snmp-generator` → `{ "ok", "message", "output" }` where `output` is the dry-run text. Before returning, the service must store the candidate as file id `candidate-snmp.yml` on app `snmp-generator`. The UI then diffs that content against `snmp-exporter` / `snmp.yml` and writes it only when the operator presses **Use as live snmp.yml** (PUT with `apply: true`).

App id for the syslog shipper is `promtail`. Container names in the mock are `<service>-ntt`.

## Role gating in the UI

The server is the authority. The UI also:

- Hides Settings → Applications from Operator and Read-only.
- Disables actions whose `roles` omit the signed-in role, and disables every `dangerous` action unless the role is Administrator.
- Treats `postgres` and `host` as read-only for every role (`readOnlyReason` on the file).
- Treats `caddy` as Administrator-only for edits (`adminOnly` in the mock; the live service should return `editable: false` for Engineers).

Masked secrets are the literal token `__SECRET__:<name>`. The editor shows them as locked chips and rejects edits that touch those ranges.
