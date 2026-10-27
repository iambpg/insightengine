"""Process settings. Paths come from the environment; nothing here is a secret value."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _truthy(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    config_root: str
    apps_file: str
    database_url: str
    history_dir: str
    cookie_secure: bool
    cookie_name: str
    setup_token_file: str
    client_slug: str
    public_host: str
    docker_proxy_url: str
    scheduler: bool
    netbox_url: str
    netbox_token_file: str
    netdisco_database_url: str
    netdisco_out_dir: str
    mib_dir: str
    candidate_dir: str
    generator_bin: str
    prometheus_url: str = "http://prometheus:9090"
    alertmanager_url: str = "http://alertmanager:9093"
    ca_file: str = "/etc/ie-certs/ca.crt"
    fleet_cache_seconds: float = 8.0
    alert_webhook_token_file: str = ""
    max_body: int = 6 * 1024 * 1024
    max_edit: int = 5 * 1024 * 1024
    mib_file_max: int = 2 * 1024 * 1024
    mib_total_max: int = 20 * 1024 * 1024
    history_keep: int = 50
    history_days: int = 90
    lockout_failures: int = 5
    lockout_minutes: int = 15
    session_hours: int = 12

    @staticmethod
    def from_env() -> "Settings":
        root = os.environ.get("CONFIG_ROOT", "/opt/insightengine")
        return Settings(
            config_root=root,
            apps_file=os.environ.get("APPS_FILE", os.path.join(os.path.dirname(os.path.dirname(__file__)), "apps.yml")),
            database_url=os.environ.get("DATABASE_URL", "sqlite:////tmp/ie-config.db"),
            history_dir=os.environ.get("HISTORY_DIR", os.path.join(root, "data", "config-history")),
            cookie_secure=_truthy("COOKIE_SECURE", "1"),
            cookie_name=os.environ.get("SESSION_COOKIE", "ie_session"),
            setup_token_file=os.environ.get("SETUP_TOKEN_FILE", "/run/secrets/setup_token"),
            client_slug=os.environ.get("CLIENT_SLUG", "unconfigured"),
            public_host=os.environ.get("PUBLIC_HOST", "localhost"),
            docker_proxy_url=os.environ.get("DOCKER_PROXY_URL", "http://ie-config-docker-proxy:2375"),
            scheduler=_truthy("IE_CONFIG_SCHEDULER", "1"),
            netbox_url=os.environ.get("NETBOX_URL", "http://netbox:8080").rstrip("/"),
            netbox_token_file=os.environ.get("NETBOX_TOKEN_FILE", os.path.join(root, "secrets", "prometheus", "netbox.token")),
            netdisco_database_url=os.environ.get("NETDISCO_DATABASE_URL", ""),
            netdisco_out_dir=os.environ.get("NETDISCO_OUT_DIR", "/var/lib/ie/netdisco-local"),
            mib_dir=os.environ.get("MIB_DIR", os.path.join(root, "snmp", "mibs")),
            candidate_dir=os.environ.get("CANDIDATE_DIR", os.path.join(root, "data", "config-history", "candidates")),
            generator_bin=os.environ.get("GENERATOR_BIN", "/usr/local/bin/generator"),
            prometheus_url=os.environ.get("PROMETHEUS_URL", "http://prometheus:9090").rstrip("/"),
            alertmanager_url=os.environ.get("ALERTMANAGER_URL", "http://alertmanager:9093").rstrip("/"),
            ca_file=os.environ.get("IE_CA_FILE", "/etc/ie-certs/ca.crt"),
            fleet_cache_seconds=float(os.environ.get("FLEET_CACHE_SECONDS", "8") or "8"),
            alert_webhook_token_file=os.environ.get("ALERT_WEBHOOK_TOKEN_FILE", ""),
        )
