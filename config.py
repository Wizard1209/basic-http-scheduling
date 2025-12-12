import os

PROXY_API_KEY = os.environ['PROXY_API_KEY']

# Redis configuration
REDIS_HOST = os.getenv('REDIS_HOST', 'redis')
REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))
REDIS_DB = int(os.getenv('REDIS_DB', '0'))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', None)

API_HOST = os.getenv('API_HOST', '0.0.0.0')
API_PORT = int(os.getenv('API_PORT', '8000'))
LOGGING_LEVEL = os.getenv('LOGGING_LEVEL', 'INFO')

# Queue configuration
DELAYED_QUEUE_KEY = 'queue'  # Single sorted set for all jobs
REQUEST_DATA_PREFIX = 'request:'

# Worker configuration
POLL_INTERVAL_SECONDS = 1.0  # Poll every 1 second

# Unified logging configuration
LOG_FORMAT = "%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_ACCESS_FORMAT = '%(asctime)s.%(msecs)03d [INFO] HTTP_ACCESS client=%(client_addr)s request="%(request_line)s" status=%(status_code)s'

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": LOG_FORMAT,
            "datefmt": LOG_DATE_FORMAT,
        },
        "access": {
            "()": "uvicorn.logging.AccessFormatter",
            "fmt": LOG_ACCESS_FORMAT,
            "datefmt": LOG_DATE_FORMAT,
        },
    },
    "handlers": {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
        },
        "access": {
            "formatter": "access",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
        },
    },
    "loggers": {
        "uvicorn": {"handlers": ["default"], "level": LOGGING_LEVEL, "propagate": False},
        "uvicorn.error": {"level": LOGGING_LEVEL},
        "uvicorn.access": {"handlers": ["access"], "level": LOGGING_LEVEL, "propagate": False},
    },
    "root": {
        "level": LOGGING_LEVEL,
        "handlers": ["default"],
    },
}
