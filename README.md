# HTTP Delay Proxy

Self-hosted HTTP proxy for scheduling delayed message delivery. Accepts requests and forwards them after a specified delay (0 seconds to ~68 years).

## What & Why

**What:** Simple API - target URL in path, delay in header, forwards with original headers/body.

**Why:** Replaces unreliable third-party SaaS HTTP schedulers

**How:** Redis sorted sets with timestamp-based job scheduling. At-least-once delivery guarantee.

## Tech Stack

- Python 3.13 + uv
- FastAPI + uvloop (high-performance HTTP API)
- Redis sorted sets (timestamp-based scheduling)
- Docker

## Log Events Reference

Format: `YYYY-MM-DD HH:MM:SS.mmm [LEVEL] EVENT key=value ...`

### Startup
| Event | Level | Description |
|-------|-------|-------------|
| `APP_START` | INFO | Application starting |
| `EVENT_LOOP` | INFO | Event loop type |
| `REDIS_CONNECT` | INFO | Redis connection established |
| `WORKER_TASK` | INFO | Background worker task created |
| `WORKER_START` | INFO | Worker polling loop started |

### Request Lifecycle
| Event | Level | Description |
|-------|-------|-------------|
| `HTTP_ACCESS` | INFO | Uvicorn access log |
| `REQUEST` | INFO | Incoming scheduling request |
| `AUTH_FAIL` | WARN | API key validation failed |
| `BODY_PARSE` | WARN | JSON body parsing failed |
| `ENQUEUE` | INFO | Job added to queue |
| `ENQUEUE_FAIL` | ERROR | Failed to add job to queue |

### Worker
| Event | Level | Description |
|-------|-------|-------------|
| `BATCH_ACQUIRE` | INFO | Jobs retrieved from queue |
| `PROCESS` | INFO | Processing a job |
| `FORWARD` | INFO | Starting HTTP forward |
| `RESPONSE` | INFO | HTTP forward completed |
| `FORWARD_ERROR` | ERROR | HTTP forward failed |
| `BATCH_DONE` | INFO | Batch processing complete |
| `WORKER_ERROR` | ERROR | Unexpected worker error |

### Redis (DEBUG level)
| Event | Level | Description |
|-------|-------|-------------|
| `REDIS_ZADD` | DEBUG | Job added to sorted set |
| `REDIS_ZRANGEBYSCORE` | DEBUG | Jobs queried |
| `REDIS_ZREMRANGEBYSCORE` | DEBUG | Jobs removed |

### Shutdown
| Event | Level | Description |
|-------|-------|-------------|
| `REDIS_CLOSE` | INFO | Redis connection closed |
| `SHUTDOWN` | INFO | Application shutdown complete |

