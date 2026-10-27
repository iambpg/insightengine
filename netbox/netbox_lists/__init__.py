from .apps import ListsConfig, config

# NetBox loads PLUGINS by importing this package and reading `config`
# (netbox/settings.py: plugin.config must be a PluginConfig subclass).
default_app_config = "netbox_lists.apps.ListsConfig"
__all__ = ["ListsConfig", "config"]
