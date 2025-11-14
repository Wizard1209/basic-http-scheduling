import logging
import time
import json
from typing import Optional
import redis.asyncio as aioredis
import config
from models import DelayedRequest

logger = logging.getLogger(__name__)

_redis_client: Optional[aioredis.Redis] = None

# Lua script for atomic job acquisition (prevents race conditions)
ACQUIRE_JOB_SCRIPT = """
local delayed_key = KEYS[1]
local processing_key = KEYS[2]
local current_time = tonumber(ARGV[1])
local processing_timeout = tonumber(ARGV[2])

-- Get the first ready job (score <= current_time)
local jobs = redis.call('ZRANGEBYSCORE', delayed_key, '-inf', current_time, 'LIMIT', 0, 1)

if #jobs == 0 then
    return nil
end

local job_id = jobs[1]

-- Move to processing set with timeout score
local processing_score = current_time + processing_timeout
redis.call('ZADD', processing_key, processing_score, job_id)
redis.call('ZREM', delayed_key, job_id)

return job_id
"""


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
    Member = request_id
    """
    client = await get_redis_client()

    # Calculate execution timestamp (milliseconds)
    execution_time_ms = int((time.time() + delay_seconds) * 1000)

    # Store request data in hash
    request_key = f"{config.REQUEST_DATA_PREFIX}{request.request_id}"
    await client.hset(
        request_key,
        mapping={
            'target_url': request.target_url,
            'method': request.method,
            'headers': json.dumps(request.headers),
            'body': json.dumps(request.body) if request.body else '',
            'timestamp': request.timestamp.isoformat(),
            'delay_seconds': str(delay_seconds)
        }
    )

    # Add to delayed queue sorted set
    await client.zadd(
        config.DELAYED_QUEUE_KEY,
        {request.request_id: execution_time_ms}
    )

    logger.info(
        f'[{request.request_id}] Enqueued with execution time: '
        f'{execution_time_ms}ms (delay={delay_seconds}s)'
    )


async def acquire_ready_job() -> Optional[str]:
    """
    Atomically acquire a ready job using Lua script.

    Returns job_id if available, None otherwise.
    """
    client = await get_redis_client()

    current_time_ms = int(time.time() * 1000)
    processing_timeout_ms = int(config.PROCESSING_TIMEOUT_SECONDS * 1000)

    # Register Lua script
    acquire_script = client.register_script(ACQUIRE_JOB_SCRIPT)

    # Execute atomic acquisition
    job_id = await acquire_script(
        keys=[config.DELAYED_QUEUE_KEY, config.PROCESSING_QUEUE_KEY],
        args=[current_time_ms, processing_timeout_ms]
    )

    return job_id


async def get_request_data(request_id: str) -> Optional[DelayedRequest]:
    """Retrieve request data from Redis hash."""
    client = await get_redis_client()

    request_key = f"{config.REQUEST_DATA_PREFIX}{request_id}"
    data = await client.hgetall(request_key)

    if not data:
        return None

    # Reconstruct DelayedRequest object
    from datetime import datetime
    return DelayedRequest(
        request_id=request_id,
        target_url=data['target_url'],
        method=data['method'],
        headers=json.loads(data['headers']),
        body=json.loads(data['body']) if data['body'] else None,
        timestamp=datetime.fromisoformat(data['timestamp']),
        delay_seconds=int(data['delay_seconds'])
    )


async def complete_job(request_id: str) -> None:
    """Remove job from processing set and delete request data."""
    client = await get_redis_client()

    # Remove from processing set
    await client.zrem(config.PROCESSING_QUEUE_KEY, request_id)

    # Delete request data
    request_key = f"{config.REQUEST_DATA_PREFIX}{request_id}"
    await client.delete(request_key)

    logger.info(f'[{request_id}] Job completed and removed')


async def recover_abandoned_jobs() -> int:
    """
    Recover jobs abandoned due to worker crashes.

    Moves jobs in processing set with expired timeout back to delayed queue.
    """
    client = await get_redis_client()

    current_time_ms = int(time.time() * 1000)

    # Find abandoned jobs (processing score < current time)
    abandoned = await client.zrangebyscore(
        config.PROCESSING_QUEUE_KEY,
        '-inf',
        current_time_ms
    )

    if not abandoned:
        return 0

    # Move back to delayed queue with immediate execution
    for job_id in abandoned:
        await client.zadd(
            config.DELAYED_QUEUE_KEY,
            {job_id: current_time_ms}
        )
        await client.zrem(config.PROCESSING_QUEUE_KEY, job_id)
        logger.warning(f'[{job_id}] Recovered abandoned job')

    return len(abandoned)


async def get_queue_stats() -> dict:
    """Get current queue statistics for monitoring."""
    client = await get_redis_client()

    delayed_count = await client.zcard(config.DELAYED_QUEUE_KEY)
    processing_count = await client.zcard(config.PROCESSING_QUEUE_KEY)

    # Get Redis memory info
    info = await client.info('memory')

    return {
        'delayed_jobs': delayed_count,
        'processing_jobs': processing_count,
        'redis_memory_used_mb': info['used_memory'] / 1024 / 1024,
        'redis_connected': True
    }
