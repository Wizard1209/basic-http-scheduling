import logging
import time
import orjson
import redis.asyncio as aioredis
import config
from models import DelayedRequest

logger = logging.getLogger(__name__)

_redis_client: aioredis.Redis | None = None


async def get_redis_client() -> aioredis.Redis:
    """Get or create Redis connection."""
    global _redis_client
    if _redis_client is None:
        _redis_client = await aioredis.from_url(
            f"redis://{config.REDIS_HOST}:{config.REDIS_PORT}/{config.REDIS_DB}",
            password=config.REDIS_PASSWORD,
            encoding="utf-8",
            decode_responses=True,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
        )
        logger.info(f'Connected to Redis at {config.REDIS_HOST}:{config.REDIS_PORT}')
    return _redis_client


async def close_redis_client() -> None:
    """Close Redis connection."""
    global _redis_client
    if _redis_client:
        await _redis_client.close()
        logger.info('Redis connection closed')
        _redis_client = None


async def enqueue_delayed_request(
    request: DelayedRequest,
    delay_seconds: int
) -> None:
    """
    Enqueue a delayed request using Redis sorted set.

    Score = current_time + delay_seconds (in milliseconds)
    Member = JSON-serialized request data (no separate hash needed)
    """
    client = await get_redis_client()

    # Calculate execution timestamp (milliseconds)
    execution_time_ms = int((time.time() + delay_seconds) * 1000)

    # Serialize entire request as JSON to store in sorted set member
    request_data = {
        'request_id': request.request_id,
        'target_url': request.target_url,
        'method': request.method,
        'headers': request.headers,
        'body': request.body,
        'timestamp': request.timestamp.isoformat(),
        'delay_seconds': delay_seconds
    }
    # orjson.dumps() returns bytes, decode to str for Redis
    request_json = orjson.dumps(request_data).decode('utf-8')

    # Add to queue sorted set with request data as member
    await client.zadd(
        config.DELAYED_QUEUE_KEY,
        {request_json: execution_time_ms}
    )

    logger.info(
        f'[{request.request_id}] Enqueued with execution time: '
        f'{execution_time_ms}ms (delay={delay_seconds}s)'
    )


async def acquire_ready_jobs() -> tuple[list[DelayedRequest], float]:
    """
    Retrieve ALL ready jobs using ZRANGEBYSCORE (batch retrieval).

    Uses ZRANGEBYSCORE to get all jobs with score <= current_time.
    Returns tuple of (jobs_list, max_score_retrieved).
    The max_score is used later for cleanup with ZREMRANGEBYSCORE.

    Returns empty list and -inf if no jobs ready.
    """
    client = await get_redis_client()

    current_time_ms = int(time.time() * 1000)

    # ZRANGEBYSCORE: Get all jobs with score from -inf to current_time
    # Returns: [(member, score), (member, score), ...] with withscores=True
    result = await client.zrangebyscore(
        config.DELAYED_QUEUE_KEY,
        '-inf',
        current_time_ms,
        withscores=True
    )

    if not result:
        # Queue is empty or no jobs ready
        return [], float('-inf')

    # Parse all retrieved jobs
    from datetime import datetime
    jobs = []
    max_score = float('-inf')

    # Result with withscores=True is: [(member1, score1), (member2, score2), ...]
    for item in result:
        request_json, score = item
        score = float(score)

        # Track max score for cleanup
        max_score = max(max_score, score)

        # Decode if bytes
        if isinstance(request_json, bytes):
            request_json = request_json.decode('utf-8')

        # Parse request data using orjson
        data = orjson.loads(request_json.encode('utf-8') if isinstance(request_json, str) else request_json)
        request = DelayedRequest(
            request_id=data['request_id'],
            target_url=data['target_url'],
            method=data['method'],
            headers=data['headers'],
            body=data['body'],
            timestamp=datetime.fromisoformat(data['timestamp']),
            delay_seconds=data['delay_seconds']
        )
        jobs.append(request)

    logger.debug(f'Acquired {len(jobs)} ready jobs (max_score={max_score}, current={current_time_ms})')
    return jobs, max_score


async def cleanup_processed_jobs(max_score: float) -> int:
    """
    Remove processed jobs from queue using ZREMRANGEBYSCORE.

    Removes all jobs with score from -inf to max_score (inclusive).
    This should be called after successfully processing a batch of jobs.

    Args:
        max_score: The maximum score from the batch that was processed

    Returns:
        Number of jobs removed from queue
    """
    if max_score == float('-inf'):
        # No jobs to clean up
        return 0

    client = await get_redis_client()

    # Remove all jobs with score <= max_score
    removed = await client.zremrangebyscore(
        config.DELAYED_QUEUE_KEY,
        '-inf',
        max_score
    )

    logger.debug(f'Cleaned up {removed} processed jobs (score <= {max_score})')
    return removed


async def get_queue_stats() -> dict:
    """Get current queue statistics for monitoring."""
    client = await get_redis_client()

    delayed_count = await client.zcard(config.DELAYED_QUEUE_KEY)

    # Get Redis memory info
    info = await client.info('memory')

    return {
        'delayed_jobs': delayed_count,
        'redis_memory_used_mb': info['used_memory'] / 1024 / 1024,
        'redis_connected': True
    }
