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
DELAYED_QUEUE_KEY = 'delayed_requests'
PROCESSING_QUEUE_KEY = 'processing_requests'
REQUEST_DATA_PREFIX = 'request:'

# Worker configuration
POLL_INTERVAL_SECONDS = 1.0  # Poll every 1 second
PROCESSING_TIMEOUT_SECONDS = 3600  # 1 hour timeout for abandoned jobs
BATCH_SIZE = 10  # Process up to 10 jobs per poll
