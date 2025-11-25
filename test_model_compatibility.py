"""
Backwards compatibility test: OLD serialization -> NEW deserialization.
"""
import orjson  # dev dependency - only used to replicate OLD serialization
from datetime import datetime, timezone
from pydantic import BaseModel
from models import DelayedRequest as NewDelayedRequest


class OldDelayedRequest(BaseModel):
    """Model as it was BEFORE this change."""
    request_id: str
    target_url: str
    method: str = 'POST'
    headers: dict[str, str]
    body: dict | None = None
    timestamp: datetime
    delay_seconds: int


def old_serialize(request: OldDelayedRequest, delay_seconds: int) -> str:
    """Exact serialization from OLD enqueue_delayed_request() - used orjson."""
    request_data = {
        'request_id': request.request_id,
        'target_url': request.target_url,
        'method': request.method,
        'headers': request.headers,
        'body': request.body,
        'timestamp': request.timestamp.isoformat(),
        'delay_seconds': delay_seconds
    }
    return orjson.dumps(request_data).decode('utf-8')


def new_deserialize(request_json: str) -> NewDelayedRequest:
    """Deserialization from NEW acquire_ready_jobs() - uses pydantic-core."""
    return NewDelayedRequest.model_validate_json(request_json)


def test_old_to_new_compatibility():
    """Job enqueued by OLD version -> processed by NEW version."""
    old_request = OldDelayedRequest(
        request_id="notif-12345",
        target_url="https://api.example.com/webhook",
        headers={"content-type": "application/json"},
        body={"message": "reminder"},
        timestamp=datetime(2025, 11, 25, 10, 0, 0, tzinfo=timezone.utc),
        delay_seconds=3600,
    )

    json_in_redis = old_serialize(old_request, delay_seconds=3600)
    new_request = new_deserialize(json_in_redis)

    assert new_request.request_id == old_request.request_id
    assert new_request.target_url == old_request.target_url
    assert new_request.body == old_request.body
    assert new_request.delay_seconds == 3600
    assert new_request.delay_timestamp is None
