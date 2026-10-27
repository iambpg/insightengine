from netbox.plugins import PluginConfig


class ListsConfig(PluginConfig):
    name = "netbox_lists"
    verbose_name = "InsightEngine device lists"
    description = "Prometheus HTTP service discovery used by InsightEngine"
    version = "1.0.0"
    base_url = "lists"
    min_version = "4.0.0"


config = ListsConfig
