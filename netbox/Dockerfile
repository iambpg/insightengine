# InsightEngine NetBox image: stock NetBox plus the lists plugin that serves
# /api/plugins/lists/prometheus-devices/ (the endpoint Prometheus already calls).
# Build context is netbox/ (the plugin). plugins.py stays at config/netbox/plugins.py
# so Settings and the runtime bind-mount share one file. Compose passes that
# directory as the named context netbox_config.
# PyYAML is already in the NetBox venv (PyYAML==6.0.3 in the v4.6.3 requirements).
# That venv is uv-managed and has no pip executable.
ARG NETBOX_BASE_IMAGE=netboxcommunity/netbox:v4.6.3
FROM ${NETBOX_BASE_IMAGE}

COPY netbox_lists /opt/netbox/netbox/netbox_lists
COPY --from=netbox_config plugins.py /etc/netbox/config/plugins.py
