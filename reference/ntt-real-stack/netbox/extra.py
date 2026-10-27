# Production optimizations
METRICS_ENABLED = True

# Rate limiting for API
RATELIMIT_ENABLE = True
RATELIMIT_RATE = '200/hour'

# CORS settings for Grafana integration (updated for HTTPS)
CORS_ORIGIN_ALLOW_ALL = False
CORS_ORIGIN_WHITELIST = [
    'https://localhost:3000',
    'https://localhost:9090',
]

# Logging configuration
#LOGGING = {
#    'version': 1,
#    'disable_existing_loggers': False,
#    'handlers': {
#        'console': {
#            'class': 'logging.StreamHandler',
#        },
#        'file': {
#            'class': 'logging.handlers.RotatingFileHandler',
#            'filename': '/opt/netbox/logs/netbox.log',
#            'maxBytes': 1024 * 1024 * 10,  # 10 MB
#            'backupCount': 5,
#        },
#    },
#    'root': {
#        'handlers': ['console', 'file'],
#        'level': 'INFO',
#    },
#}

# Session configuration for production (HTTPS enabled)
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
