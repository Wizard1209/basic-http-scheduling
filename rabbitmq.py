import logging
import aio_pika
from aio_pika import ExchangeType, DeliveryMode
from aio_pika.abc import AbstractRobustConnection
import config
from models import DelayedRequest

logger = logging.getLogger(__name__)

_connection: AbstractRobustConnection | None = None


async def get_connection() -> AbstractRobustConnection:
    global _connection
    if _connection is None or _connection.is_closed:
        connection_url = f'amqp://{config.RABBITMQ_USER}:{config.RABBITMQ_PASS}@{config.RABBITMQ_HOST}:{config.RABBITMQ_PORT}/'
        _connection = await aio_pika.connect_robust(connection_url)
        logger.info('Connected to RabbitMQ')
    return _connection


async def setup_queues() -> None:
    connection = await get_connection()
    channel = await connection.channel()

    logger.info('Setting up RabbitMQ quorum queues with at-least-once delivery and delay buckets')

    # Processing queue: quorum queue for high availability
    await channel.declare_queue(
        config.PROCESSING_QUEUE,
        durable=True,
        arguments={
            'x-queue-type': 'quorum'
        }
    )
    logger.info(f'Processing quorum queue declared: {config.PROCESSING_QUEUE}')

    # Create delay bucket queues (reduces variance by grouping similar delays)
    bucket_info = [
        (config.DELAY_QUEUE_10M, '< 10 minutes'),
        (config.DELAY_QUEUE_1H, '10m - 1h'),
        (config.DELAY_QUEUE_24H, '1h - 24h'),
        (config.DELAY_QUEUE_24H_PLUS, '> 24h')
    ]

    for queue_name, description in bucket_info:
        await channel.declare_queue(
            queue_name,
            durable=True,
            arguments={
                'x-queue-type': 'quorum',
                'x-dead-letter-exchange': '',
                'x-dead-letter-routing-key': config.PROCESSING_QUEUE,
                'x-dead-letter-strategy': 'at-least-once',
                'x-overflow': 'reject-publish',
                'x-max-length': 1000000  # Prevent unbounded growth
            }
        )
        logger.info(f'Delay bucket queue declared: {queue_name} ({description})')

    await channel.close()


async def publish_delayed_request(
    request: DelayedRequest,
    delay_seconds: int
) -> None:
    connection = await get_connection()
    channel = await connection.channel()

    # Route to appropriate delay bucket based on delay duration
    delay_queue = config.get_delay_queue(delay_seconds)

    message = aio_pika.Message(
        body=request.model_dump_json().encode(),
        delivery_mode=DeliveryMode.PERSISTENT,
        expiration=delay_seconds
    )

    await channel.default_exchange.publish(
        message,
        routing_key=delay_queue
    )

    logger.info(
        f'[{request.request_id}] Published to {delay_queue} '
        f'with {delay_seconds}s delay'
    )

    await channel.close()


async def close_connection() -> None:
    global _connection
    if _connection and not _connection.is_closed:
        await _connection.close()
        logger.info('RabbitMQ connection closed')
        _connection = None
