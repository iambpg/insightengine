# InsightEngine customer UI

The UI source is imported here in a follow-up pull request from [iambpg/insightengine_9515](https://github.com/iambpg/insightengine_9515) (Next.js). This directory currently holds a placeholder image so `docker compose build` and `./install.sh` succeed from one clone.

- `Dockerfile` builds `insightengine-ui:local`. The container listens on port 8080 and answers `GET /healthz`.
- `Dockerfile.placeholder` is the same image. `install.sh` uses it when `ui/Dockerfile` is not present yet, and Caddy keeps serving `config/ui-placeholder/` in that fallback.
- Do not volume-mount the placeholder over the image. A real UI copied into this directory would be hidden.

`IE_UI_IMAGE` in `.env` is an optional override. When it is set to something other than `insightengine-ui:local`, `install.sh` pulls that image and does not build `ui/`.
