# Loaded by the NetBox image. The plugin package is netbox_lists; its API base_url is "lists"
# so Prometheus can call /api/plugins/lists/prometheus-devices/.
PLUGINS = ["netbox_lists"]
PLUGINS_CONFIG = {
    "netbox_lists": {
        "module_map": "/etc/ie/module-map.yml",
    },
}
