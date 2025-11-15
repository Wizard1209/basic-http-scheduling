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
