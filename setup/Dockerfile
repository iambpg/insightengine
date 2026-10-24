# First-run / settings setup service. Python standard library only (no pip deps).
# Needs the docker CLI + compose plugin to talk to the docker-socket-proxy, and bash
# + curl for scripts/migrate.sh and scripts/prom-history.sh.
ARG PY_IMAGE=python:3.12-alpine
FROM ${PY_IMAGE}
RUN apk add --no-cache docker-cli docker-cli-compose bash curl jq coreutils
WORKDIR /app
COPY server.py /app/server.py
COPY static /app/static
USER root
# Root is required: it writes .env/data in the (root/owner-created) project directory
# and runs compose. The container's only Docker access is the filtered proxy.
EXPOSE 8099
ENV PYTHONUNBUFFERED=1
CMD ["python3", "/app/server.py"]
