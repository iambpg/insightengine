# InsightEngine UI

Customer interface for InsightEngine: live device and port health, discovery approval, and editable configuration for every app in the stack (Prometheus, Alertmanager, SNMP exporter and generator, blackbox, Telegraf, Grafana, Caddy, NetBox, Netdisco, Activepieces, Loki, Promtail, Oxidized, trapd, plus read-only PostgreSQL and host status).

The UI is a Next.js 15 / React 19 app. It lives in this directory of the InsightEngine repository so one `git clone` and `./install.sh` build the whole product. It does not read anything outside this directory. See [INTEGRATION.md](INTEGRATION.md) for the build command, environment variables, and the Caddy routes it expects.

The settings and discovery calls follow the shared contract in the engine repo: `docs/settings-api.md` (iambpg/insightengine). This UI does not ship a second copy of that contract.

## Scripts

| Command            | What it does                                                                                          |
| ------------------ | ----------------------------------------------------------------------------------------------------- |
| `npm install`      | Install dependencies. Run this inside this directory.                                                 |
| `npm run dev`      | Next.js dev server on port 4028. With `NEXT_PUBLIC_IE_API_MODE` unset this is mock mode (no backend). |
| `npm run dev:mock` | Same server, with demo accounts compiled in (`NEXT_PUBLIC_IE_API_MODE=mock`).                         |
| `npm run build`    | Production build (`output: 'standalone'`). Defaults to live API mode.                                 |
| `npm run serve`    | `next start` for a non-standalone production build. Honours `PORT`.                                   |
| `npm run lint`     | ESLint.                                                                                               |
| `npm test`         | Vitest + React Testing Library.                                                                       |

## API mode

`NEXT_PUBLIC_IE_API_MODE`:

- `live` — every call is `fetch` to same-origin `/api/v1/...` (`credentials: 'include'`, `X-CSRF-Token` on writes). `GET /setup/state` is the one call that is not under `/api/v1`. This is the default for `npm run build` and for the Docker image.
- `mock` — the in-browser demo, including demo accounts. Never bake this into the image you deploy.
- unset — `live` when `NODE_ENV=production`, otherwise `mock`.

Demo passwords live only in `src/lib/mock/mockAuth.ts`. Production builds replace that module with an empty stub, so the passwords are not in the client bundle. Do not set `NEXT_PUBLIC_IE_API_MODE=mock` for a production build.

There is no `.env` in the repo. Copy `.env.example` if you want the variable set locally. `.env*` is gitignored.

## Deployment

The production image is built from the `Dockerfile` in this directory: multi-stage, non-root, Next.js standalone output, `npm ci` from the committed lockfile. It listens on port **8080** and honours `PORT` and `HOSTNAME`. `GET /healthz` returns `{ "ok": true }` and does not depend on setup or the API. The image build sets `NEXT_PUBLIC_IE_API_MODE=live`.

In this repository, leave `IE_UI_IMAGE` empty. `./install.sh` builds `insightengine-ui:local` from `Dockerfile` and starts the stack. `Dockerfile.placeholder` is only used when `Dockerfile` is absent.

```bash
git clone <this-repo> insightengine && cd insightengine
sudo ./install.sh --public-host monitor.example.com
# open https://<PUBLIC_HOST>/  -> first-run page /setup/  -> then this UI
```

Caddy sends `/api/v1/*` to `ie-config`, `/setup/*` to the setup service, `/healthz` to this UI, and the rest of the site to this UI after the setup gate. Details and the JSON shapes this UI expects beyond the prose contract are in [INTEGRATION.md](INTEGRATION.md).

## Placeholders to replace

These three files were not in the source export. They are generated stand-ins. Replace them with the originals from `iambpg/insightengine_9515`:

- `public/assets/images/app_logo.png` (brand colours Midnight Navy `#0B1220` and Signal Cyan `#36CFFF`)
- `public/assets/images/no_image.png`
- `public/favicon.ico`
