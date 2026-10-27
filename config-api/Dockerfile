# ie-config: settings API. Validator binaries are copied from the same image tags
# the stack runs. This image is built by install.sh; it was not executed in CI
# unless a Docker daemon was available (see the pull request notes).
FROM prom/prometheus:v3.11.3 AS prom
FROM prom/alertmanager:v0.32.0 AS am
FROM prom/snmp-exporter:v0.30.1 AS snmp
FROM prom/blackbox-exporter:v0.28.0 AS blackbox
FROM caddy:2.11.2 AS caddy
FROM telegraf:1.38.3 AS telegraf

FROM golang:1.24-bookworm AS generator
RUN apt-get update \
 && apt-get install -y --no-install-recommends git gcc libc6-dev libsnmp-dev \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git clone --depth 1 --branch v0.30.1 https://github.com/prometheus/snmp_exporter.git .
WORKDIR /src/generator
RUN go build -o /out/generator .

FROM python:3.12-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends libsnmp40 ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=prom /bin/promtool /usr/local/bin/promtool
COPY --from=am /bin/amtool /usr/local/bin/amtool
COPY --from=snmp /bin/snmp_exporter /usr/local/bin/snmp_exporter
COPY --from=blackbox /bin/blackbox_exporter /usr/local/bin/blackbox_exporter
COPY --from=caddy /usr/bin/caddy /usr/local/bin/caddy
COPY --from=telegraf /usr/bin/telegraf /usr/local/bin/telegraf
COPY --from=generator /out/generator /usr/local/bin/generator
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ie_config ./ie_config
COPY apps.yml ./apps.yml
ENV APPS_FILE=/app/apps.yml \
    IE_CONFIG_PORT=8080 \
    PYTHONUNBUFFERED=1
EXPOSE 8080
# Writes host config files via the install-directory mount. Documented in docs/config-api.md.
USER root
CMD ["python", "-m", "ie_config"]
