# InsightEngine UI. Build context is this directory, not the repo root.
# With IE_UI_IMAGE empty, ./install.sh builds insightengine-ui:local from this file.
# npm ci uses the committed lockfile. NEXT_PUBLIC_IE_API_MODE=live is set for the build.
# The process listens on port 8080 and serves GET /healthz.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
ENV NEXT_PUBLIC_IE_API_MODE=live
RUN npm run build

FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=8080
ENV HOSTNAME=0.0.0.0
RUN addgroup -g 1001 -S ie && adduser -S -u 1001 -G ie ie
COPY --from=build --chown=ie:ie /app/public ./public
COPY --from=build --chown=ie:ie /app/.next/standalone ./
COPY --from=build --chown=ie:ie /app/.next/static ./.next/static
USER ie
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:'+(process.env.PORT||8080)+'/healthz').then((r)=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "server.js"]
