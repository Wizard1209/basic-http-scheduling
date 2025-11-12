from pydantic import BaseModel
from datetime import datetime


class DelayedRequest(BaseModel):
    request_id: str
    target_url: str
    method: str = 'POST'
    headers: dict[str, str]
    body: dict | None = None
    timestamp: datetime
    delay_seconds: int
