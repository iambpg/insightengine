# Production settings imported by the NetBox image from /etc/netbox/config/extra.py.
# No secrets belong in this file.
METRICS_ENABLED = True

RATELIMIT_ENABLE = True
RATELIMIT_RATE = "200/hour"

CORS_ORIGIN_ALLOW_ALL = False

SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
