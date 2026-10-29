# Production settings imported by the NetBox image from /etc/netbox/config/extra.py.
# No secrets belong in this file.
import os

# The container healthcheck connects to 127.0.0.1. Django compares that Host
# header with ALLOWED_HOSTS, and the image only adds "localhost" on its own.
_allowed_hosts = [host for host in os.environ.get("ALLOWED_HOSTS", "").split(" ") if host]
for _host in ("localhost", "127.0.0.1"):
    if _host not in _allowed_hosts:
        _allowed_hosts.append(_host)
ALLOWED_HOSTS = _allowed_hosts

METRICS_ENABLED = True

RATELIMIT_ENABLE = True
RATELIMIT_RATE = "200/hour"

CORS_ORIGIN_ALLOW_ALL = False

SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
