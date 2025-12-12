import logging
import time
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
        logger.info(f'REDIS_CONNECT host={config.REDIS_HOST} port={config.REDIS_PORT}')
    return _redis_client


async def close_redis_client() -> None:
    """Close Redis connection."""
    global _redis_client
    if _redis_client:
        await _redis_client.close()
        logger.info('REDIS_CLOSE status=ok')
        _redis_client = None


async def enqueue_request(request: DelayedRequest, execution_time_ms: int) -> None:
    """
    Enqueue a request using Redis sorted set.

    Args:
        request: The DelayedRequest to enqueue (already fully formed)
        execution_time_ms: Unix timestamp in milliseconds when job should execute
    """
    client = await get_redis_client()

    # Serialize using Pydantic's model_dump_json (uses pydantic-core Rust serializer)
    request_json = request.model_dump_json()

    # Add to queue sorted set with request data as member
    # NX flag: only add new elements, don't update existing ones
    added = await client.zadd(
        config.DELAYED_QUEUE_KEY,
        {request_json: execution_time_ms},
        nx=True
    )

    if added == 0:
        logger.error(f'[{request.request_id}] REDIS_ZADD status=duplicate')
        raise ValueError(f'Job {request.request_id} already exists in queue')

    logger.debug(f'[{request.request_id}] REDIS_ZADD status=ok score={execution_time_ms}')


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
    jobs = []
    max_score = float('-inf')

    # Result with withscores=True is: [(member1, score1), (member2, score2), ...]
    for item in result:
        request_json, score = item
        score = float(score)

        # Track max score for cleanup
        max_score = max(max_score, score)

        # Parse using pydantic-core (Rust JSON parser + validation in one step)
        # Handles backwards compat: missing delay_timestamp defaults to None
        request = DelayedRequest.model_validate_json(request_json)
        jobs.append(request)

    logger.debug(f'REDIS_ZRANGEBYSCORE count={len(jobs)} max_score={max_score} current_ms={current_time_ms}')
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

    logger.debug(f'REDIS_ZREMRANGEBYSCORE removed={removed} max_score={max_score}')
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
