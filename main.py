import logging
import logging.config
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

logging.config.dictConfig(config.LOGGING_CONFIG)
logger = logging.getLogger(__name__)


async def forward_request(request: DelayedRequest) -> None:
    rid = request.request_id
    url = request.target_url
    start_time = time.time()
    status = None
    error = None

    logger.info(f'FORWARD [{rid}] url={url}')

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method=request.method,
                url=url,
                headers=request.headers,
                json=request.body
            )
        status = response.status_code
    except httpx.TimeoutException:
        error = 'TIMEOUT'
    except Exception as e:
        error = f'{e.__class__.__name__}: {e}'
    finally:
        elapsed_ms = int((time.time() - start_time) * 1000)
        if status:
            logger.info(f'RESPONSE [{rid}] status={status} time={elapsed_ms}ms')
        else:
            logger.error(f'FORWARD_ERROR [{rid}] error={error} time={elapsed_ms}ms')


async def poll_and_process_jobs():
    """
    Main worker loop: polls for ready jobs and processes them in batches.

    Uses ZRANGEBYSCORE to retrieve all ready jobs, processes them all,
    then removes them with ZREMRANGEBYSCORE.
    """
    logger.info('WORKER_START mode=batch')

    while True:
        try:
            jobs, max_score = await acquire_ready_jobs()

            if jobs:
                logger.info(f'BATCH_ACQUIRE count={len(jobs)}')

                for request in jobs:
                    now = datetime.now(timezone.utc)
                    actual_delay = (now - request.timestamp).total_seconds()

                    if request.delay_seconds is not None:
                        intended_delay = request.delay_seconds
                    else:
                        intended_delay = (request.delay_timestamp - request.timestamp).total_seconds()

                    delay_diff = actual_delay - intended_delay
                    logger.info(
                        f'PROCESS [{request.request_id}] intended={intended_delay:.2f}s '
                        f'actual={actual_delay:.2f}s diff={delay_diff:+.2f}s'
                    )

                    await forward_request(request)

                removed = await cleanup_processed_jobs(max_score)
                logger.info(f'BATCH_DONE processed={len(jobs)} removed={removed}')
            else:
                await asyncio.sleep(config.POLL_INTERVAL_SECONDS)

        except Exception as e:
            logger.error(f'WORKER_ERROR error={e}', exc_info=True)
            await asyncio.sleep(config.POLL_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_redis_client()
    logger.info('REDIS_CONNECT status=ok')

    worker_task = asyncio.create_task(poll_and_process_jobs())
    logger.info('WORKER_TASK status=started')

    yield

    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

    await close_redis_client()
    logger.info('SHUTDOWN status=complete')


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
        logger.error(f'HEALTH_CHECK status=failed error={e}')
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

    logger.info(f'REQUEST [{request_id}] url={target_url}')

    if x_api_key != config.PROXY_API_KEY:
        logger.warning(f'AUTH_FAIL [{request_id}] reason=invalid_api_key')
        raise HTTPException(status_code=401, detail='Invalid API key')

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

    try:
        body = await request.json()
    except Exception as e:
        logger.warning(f'BODY_PARSE [{request_id}] error={e}')
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
        logger.info(
            f'ENQUEUE [{request_id}] url={target_url} '
            f'delay={delayed_req.get_display_delay()} exec_time_ms={execution_time_ms}'
        )

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
        logger.error(f'ENQUEUE_FAIL [{request_id}] error={e}')
        raise HTTPException(status_code=500, detail='Failed to queue request')


if __name__ == '__main__':
    import uvicorn

    logger.info(f'APP_START host={config.API_HOST} port={config.API_PORT}')

    try:
        import uvloop
        logger.info(f'EVENT_LOOP type=uvloop version={uvloop.__version__}')
        uvicorn.run(
            app,
            host=config.API_HOST,
            port=config.API_PORT,
            loop='uvloop',
            log_config=config.LOGGING_CONFIG
        )
    except ImportError:
        logger.warning('EVENT_LOOP type=asyncio note=uvloop_not_available')
        uvicorn.run(
            app,
            host=config.API_HOST,
            port=config.API_PORT,
            log_config=config.LOGGING_CONFIG
        )
