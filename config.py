import os

PROXY_API_KEY = os.environ['PROXY_API_KEY']

RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', 'rabbitmq')
RABBITMQ_PORT = int(os.getenv('RABBITMQ_PORT', '5672'))
RABBITMQ_USER = os.getenv('RABBITMQ_USER', 'guest')
RABBITMQ_PASS = os.getenv('RABBITMQ_PASS', 'guest')

API_HOST = os.getenv('API_HOST', '0.0.0.0')
API_PORT = int(os.getenv('API_PORT', '8000'))
LOGGING_LEVEL = os.getenv('LOGGING_LEVEL', 'INFO')

PROCESSING_QUEUE = 'processing_queue'

# Delay bucket configuration (reduces variance by grouping similar delays)
# Bucket boundaries in seconds
BUCKET_10M = 600      # < 10 minutes
BUCKET_1H = 3600      # < 1 hour
BUCKET_24H = 86400    # < 24 hours
# > 24 hours uses bucket_24h_plus

# Delay queue names by bucket
DELAY_QUEUE_10M = 'delay_queue_10m'       # 0s - 10m
DELAY_QUEUE_1H = 'delay_queue_1h'         # 10m - 1h
DELAY_QUEUE_24H = 'delay_queue_24h'       # 1h - 24h
DELAY_QUEUE_24H_PLUS = 'delay_queue_24h_plus'  # > 24h

# All delay queues
DELAY_QUEUES = [DELAY_QUEUE_10M, DELAY_QUEUE_1H, DELAY_QUEUE_24H, DELAY_QUEUE_24H_PLUS]


def get_delay_queue(delay_seconds: int) -> str:
    """Route message to appropriate delay queue based on delay duration."""
    if delay_seconds < BUCKET_10M:
        return DELAY_QUEUE_10M
    elif delay_seconds < BUCKET_1H:
        return DELAY_QUEUE_1H
    elif delay_seconds < BUCKET_24H:
        return DELAY_QUEUE_24H
    else:
        return DELAY_QUEUE_24H_PLUS
