from pydantic import BaseModel, model_validator
from datetime import datetime


class DelayedRequest(BaseModel):
    """
    Represents a delayed HTTP request to be scheduled.

    Supports two mutually exclusive scheduling modes:
    - delay_seconds: Relative delay from request time (legacy, for logging)
    - delay_timestamp: Absolute ISO 8601 timestamp when to execute

    For backwards compatibility with existing Redis data:
    - Old format only has delay_seconds (required)
    - New format can have either field
    """
    request_id: str
    target_url: str
    method: str = 'POST'
    headers: dict[str, str]
    body: dict | None = None
    timestamp: datetime
    # Mutually exclusive scheduling fields
    delay_seconds: int | None = None
    delay_timestamp: datetime | None = None

    @model_validator(mode='after')
    def check_scheduling_fields(self) -> 'DelayedRequest':
        if self.delay_seconds is not None and self.delay_timestamp is not None:
            raise ValueError("Only one of 'delay_seconds' or 'delay_timestamp' may be set, not both.")
        if self.delay_seconds is None and self.delay_timestamp is None:
            raise ValueError("Exactly one of 'delay_seconds' or 'delay_timestamp' must be set.")
        return self

    def get_display_delay(self) -> str:
        """Get human-readable delay description for logging."""
        if self.delay_seconds is not None:
            return f"{self.delay_seconds}s"
        else:
            return f"at {self.delay_timestamp.isoformat()}"
