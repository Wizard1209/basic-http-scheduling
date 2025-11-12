# HTTP Delay Proxy

Self-hosted HTTP proxy for scheduling delayed message delivery. Accepts requests and forwards them after a specified delay (0 seconds to ~68 years).

## What & Why

**What:** Simple API - target URL in path, delay in header, forwards with original headers/body.

**Why:** Replaces unreliable third-party SaaS HTTP schedulers

**How:** RabbitMQ quorum queues + TTL + Dead Letter Exchange with at-least-once delivery guarantee. Uses 4 delay buckets to minimize variance by grouping similar delays. The approach is not ideal but very simple

## Tech Stack

- Python 3.13 + uv
- FastAPI + uvloop (high-performance HTTP API)
- RabbitMQ 3.13+ (quorum queues with at-least-once DLX)
- aio-pika (async RabbitMQ client)
- Docker

