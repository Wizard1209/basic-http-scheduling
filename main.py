import logging
import uuid
import time
import httpx
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import JSONResponse
import aio_pika
import config
from models import DelayedRequest
from rabbitmq import get_connection, setup_queues, publish_delayed_request, close_connection

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


async def consume_processing_queue():
    connection = await get_connection()
    channel = await connection.channel()
    
    await channel.set_qos(prefetch_count=1)
    
    queue = await channel.get_queue(config.PROCESSING_QUEUE)
    
    async def process_message(message: aio_pika.IncomingMessage):
        async with message.process():
            try:
                request = DelayedRequest.model_validate_json(message.body.decode())

                # Calculate actual delay
                now = datetime.now(timezone.utc)
                actual_delay = (now - request.timestamp).total_seconds()
                delay_diff = actual_delay - request.delay_seconds

                logger.info(
                    f'[{request.request_id}] Consumed from {config.PROCESSING_QUEUE} '
                    f'(intended: {request.delay_seconds}s, actual: {actual_delay:.2f}s, '
                    f'diff: {delay_diff:+.2f}s)'
                )

                await forward_request(request)

                logger.info(f'[{request.request_id}] Message acknowledged')

            except Exception as e:
                logger.error(f'Error processing message: {e}')
                raise
    
    logger.info(f'Worker started. Consuming from {config.PROCESSING_QUEUE}')
    await queue.consume(process_message)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await setup_queues()
    
    consumer_task = asyncio.create_task(consume_processing_queue())
    logger.info('Background worker task started')
    
    yield
    
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass
    
    await close_connection()
    logger.info('Application shutdown complete')


app = FastAPI(title='Basic HTTP Scheduling', lifespan=lifespan)


@app.post('/{target_url:path}')
async def proxy_request(
    target_url: str,
    request: Request,
    x_delay_seconds: int = Header(..., alias='X-Delay-Seconds'),
    x_api_key: str = Header(..., alias='X-API-Key')
) -> JSONResponse:
    request_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc)

    logger.info(f'[{request_id}] Received request: POST {target_url}')
    
    if x_api_key != config.PROXY_API_KEY:
        logger.warning(f'[{request_id}] Invalid API key attempt')
        raise HTTPException(
            status_code=401,
            detail='Invalid API key'
        )
    
    logger.info(f'[{request_id}] API key validated')

    if x_delay_seconds < 0 or x_delay_seconds > MAX_DELAY_SECONDS:
        logger.warning(
            f'[{request_id}] Invalid delay: {x_delay_seconds}s '
            f'(must be 0-{MAX_DELAY_SECONDS})'
        )
        raise HTTPException(
            status_code=400,
            detail=f'Delay must be between 0 and {MAX_DELAY_SECONDS} seconds'
        )
    
    try:
        body = await request.json()
        logger.info(f'[{request_id}] Body parsed successfully')
    except Exception as e:
        logger.warning(f'[{request_id}] No JSON body: {e}')
        body = None
    
    headers_to_forward = {
        k: v for k, v in request.headers.items()
        if not k.lower().startswith('x-delay-')
        and k.lower() != 'x-api-key'
        and k.lower() != 'host'
        and k.lower() != 'content-length'
    }
    
    delayed_req = DelayedRequest(
        request_id=request_id,
        target_url=target_url,
        method='POST',
        headers=headers_to_forward,
        body=body,
        timestamp=timestamp,
        delay_seconds=x_delay_seconds
    )
    
    try:
        await publish_delayed_request(delayed_req, x_delay_seconds)
        logger.info(
            f'[{request_id}] Queued successfully: '
            f'{target_url} (delay={x_delay_seconds}s)'
        )
        return JSONResponse(
            status_code=201,
            content={
                'message': f'Request queued. Will be delivered in {x_delay_seconds} seconds.',
                'request_id': request_id,
                'target_url': target_url,
                'delay_seconds': x_delay_seconds
            }
        )
    except Exception as e:
        logger.error(f'[{request_id}] Failed to queue: {e}')
        raise HTTPException(status_code=500, detail='Failed to queue request')


if __name__ == '__main__':
    import uvicorn
    logger.info(f'Starting Basic HTTP Scheduling on {config.API_HOST}:{config.API_PORT}')
    uvicorn.run(
        app,
        host=config.API_HOST,
        port=config.API_PORT
    )
