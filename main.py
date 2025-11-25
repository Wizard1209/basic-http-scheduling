import logging
import uuid
import time
import httpx
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import JSONResponse
import config
from models import DelayedRequest
from redis_queue import (
    get_redis_client,
    close_redis_client,
    enqueue_request,
    acquire_ready_jobs,
    cleanup_processed_jobs,
    get_queue_stats
)

# Maximum delay: 2,147,483,647 seconds (max 32-bit int, ~68 years)
MAX_DELAY_SECONDS = 2147483647

logging.basicConfig(
    level=config.LOGGING_LEVEL,
    format='[%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


async def forward_request(request: DelayedRequest) -> None:
    start_time = time.time()
    
    try:
        logger.info(
            f'[{request.request_id}] Forwarding {request.method} '
            f'{request.target_url}'
        )
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method=request.method,
                url=request.target_url,
                headers=request.headers,
                json=request.body
            )
            
            elapsed = int((time.time() - start_time) * 1000)
            logger.info(
                f'[{request.request_id}] Response: '
                f'{response.status_code} ({elapsed}ms)'
            )
    
    except httpx.TimeoutException:
        logger.error(
            f'[{request.request_id}] Timeout after 30s '
            f'forwarding to {request.target_url}'
        )
    except httpx.RequestError as e:
        logger.error(
            f'[{request.request_id}] Request error: {e.__class__.__name__} - {e}'
        )
    except Exception as e:
        logger.error(
            f'[{request.request_id}] Unexpected error: {e.__class__.__name__} - {e}'
        )


async def poll_and_process_jobs():
    """
    Main worker loop: polls for ready jobs and processes them in batches.

    Uses ZRANGEBYSCORE to retrieve all ready jobs, processes them all,
    then removes them with ZREMRANGEBYSCORE.
    """
    logger.info('Worker started - polling for ready jobs (batch mode)')

    while True:
        try:
            # Acquire ALL ready jobs in batch
            jobs, max_score = await acquire_ready_jobs()

            if jobs:
                # Jobs acquired - process all of them
                logger.info(f'Acquired {len(jobs)} jobs for batch processing')

                # Process each job
                for request in jobs:
                    now = datetime.now(timezone.utc)
                    actual_delay = (now - request.timestamp).total_seconds()

                    if request.delay_seconds is not None:
                        intended_delay = request.delay_seconds
                    else:
                        intended_delay = (request.delay_timestamp - request.timestamp).total_seconds()

                    delay_diff = actual_delay - intended_delay
                    logger.info(
                        f'[{request.request_id}] Processing (intended: {intended_delay:.2f}s, '
                        f'actual: {actual_delay:.2f}s, diff: {delay_diff:+.2f}s)'
                    )

                    # Forward the request (never raises exceptions)
                    await forward_request(request)

                # All jobs processed - remove them from queue
                removed = await cleanup_processed_jobs(max_score)
                logger.info(f'Batch complete: processed {len(jobs)} jobs, removed {removed} from queue')

                # Don't sleep - immediately check for next batch
            else:
                # No jobs ready - sleep before next poll
                await asyncio.sleep(config.POLL_INTERVAL_SECONDS)

        except Exception as e:
            logger.error(f'Worker error: {e}', exc_info=True)
            await asyncio.sleep(config.POLL_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize Redis connection
    await get_redis_client()
    logger.info('Redis connection established')

    # Start worker task
    worker_task = asyncio.create_task(poll_and_process_jobs())
    logger.info('Background worker task started')

    yield

    # Shutdown
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

    await close_redis_client()
    logger.info('Application shutdown complete')


app = FastAPI(title='Basic HTTP Scheduling', lifespan=lifespan)


@app.get('/health')
async def health_check():
    """Health check endpoint with queue statistics."""
    try:
        stats = await get_queue_stats()
        # Check which event loop is being used
        import asyncio
        loop = asyncio.get_running_loop()
        loop_type = f"{type(loop).__module__}.{type(loop).__name__}"

        return {
            'status': 'healthy',
            'event_loop': loop_type,
            **stats
        }
    except Exception as e:
        logger.error(f'Health check failed: {e}')
        return JSONResponse(
            status_code=503,
            content={'status': 'unhealthy', 'error': str(e)}
        )


def parse_schedule_at(value: str) -> datetime:
    """Parse ISO 8601 timestamp, require timezone."""
    try:
        # Handle 'Z' suffix (replace with +00:00 for fromisoformat)
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as e:
        raise ValueError(f"Invalid ISO 8601 format: {e}")

    if dt.tzinfo is None:
        raise ValueError("Timezone required (use 'Z' suffix or explicit offset like '+00:00')")

    return dt


@app.post('/{target_url:path}')
async def proxy_request(
    target_url: str,
    request: Request,
    x_delay_seconds: int | None = Header(None, alias='X-Delay-Seconds'),
    x_schedule_at: str | None = Header(None, alias='X-Schedule-At'),
    x_api_key: str = Header(..., alias='X-API-Key')
) -> JSONResponse:
    request_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc)

    logger.info(f'[{request_id}] Received request: POST {target_url}')

    # Validate API key
    if x_api_key != config.PROXY_API_KEY:
        logger.warning(f'[{request_id}] Invalid API key attempt')
        raise HTTPException(status_code=401, detail='Invalid API key')

    logger.info(f'[{request_id}] API key validated')

    # Validate scheduling headers (mutually exclusive)
    if x_delay_seconds is not None and x_schedule_at is not None:
        raise HTTPException(
            status_code=400,
            detail='Use X-Delay-Seconds OR X-Schedule-At, not both'
        )
    if x_delay_seconds is None and x_schedule_at is None:
        raise HTTPException(
            status_code=400,
            detail='Requires X-Delay-Seconds or X-Schedule-At header'
        )

    # Calculate execution_time_ms and build model fields
    delay_seconds_field: int | None = None
    delay_timestamp_field: datetime | None = None

    if x_delay_seconds is not None:
        if x_delay_seconds < 0 or x_delay_seconds > MAX_DELAY_SECONDS:
            raise HTTPException(
                status_code=400,
                detail=f'Delay must be between 0 and {MAX_DELAY_SECONDS} seconds'
            )
        execution_time_ms = int((time.time() + x_delay_seconds) * 1000)
        delay_seconds_field = x_delay_seconds
    else:
        # x_schedule_at is set
        try:
            schedule_dt = parse_schedule_at(x_schedule_at)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        execution_time_ms = int(schedule_dt.timestamp() * 1000)
        delay_timestamp_field = schedule_dt

    # Parse body
    try:
        body = await request.json()
        logger.info(f'[{request_id}] Body parsed successfully')
    except Exception as e:
        logger.warning(f'[{request_id}] No JSON body: {e}')
        body = None

    # Filter headers
    headers_to_forward = {
        k: v for k, v in request.headers.items()
        if not k.lower().startswith('x-delay-')
        and k.lower() not in ('x-api-key', 'x-schedule-at', 'host', 'content-length')
    }

    delayed_req = DelayedRequest(
        request_id=request_id,
        target_url=target_url,
        method='POST',
        headers=headers_to_forward,
        body=body,
        timestamp=timestamp,
        delay_seconds=delay_seconds_field,
        delay_timestamp=delay_timestamp_field,
    )

    try:
        await enqueue_request(delayed_req, execution_time_ms)
        logger.info(f'[{request_id}] Queued: {target_url} ({delayed_req.get_display_delay()})')

        # Build response based on scheduling method
        response_content = {
            'message': f'Request queued.',
            'request_id': request_id,
            'target_url': target_url,
        }
        if delay_seconds_field is not None:
            response_content['delay_seconds'] = delay_seconds_field
        else:
            response_content['schedule_at'] = delay_timestamp_field.isoformat()

        return JSONResponse(status_code=201, content=response_content)
    except Exception as e:
        logger.error(f'[{request_id}] Failed to queue: {e}')
        raise HTTPException(status_code=500, detail='Failed to queue request')


if __name__ == '__main__':
    import uvicorn
    logger.info(f'Starting Basic HTTP Scheduling on {config.API_HOST}:{config.API_PORT}')

    # Check if uvloop is available and use it with uvicorn
    try:
        import uvloop
        logger.info(f'Using uvloop {uvloop.__version__} for event loop')
        uvicorn.run(
            app,
            host=config.API_HOST,
            port=config.API_PORT,
            loop='uvloop'
        )
    except ImportError:
        logger.warning('uvloop not available, using default asyncio event loop')
        uvicorn.run(
            app,
            host=config.API_HOST,
            port=config.API_PORT
        )
