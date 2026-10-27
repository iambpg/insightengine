# InsightEngine NetBox image: stock NetBox plus the lists plugin that serves
# /api/plugins/lists/prometheus-devices/ (the endpoint Prometheus already calls).
ARG NETBOX_BASE_IMAGE=netboxcommunity/netbox:v4.6.3
FROM ${NETBOX_BASE_IMAGE}

COPY netbox_lists /opt/netbox/netbox/netbox_lists
COPY plugins.py /etc/netbox/config/plugins.py
# The plugin reads module-map.yml. The stock image does not ship PyYAML in the venv.
RUN /opt/netbox/venv/bin/pip install --no-cache-dir 'pyyaml==6.0.2'
