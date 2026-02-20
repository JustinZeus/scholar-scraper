from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

QUEUE_STATUS_QUEUED = "queued"
QUEUE_STATUS_RETRYING = "retrying"
QUEUE_STATUS_DROPPED = "dropped"


@dataclass(frozen=True)
class QueueListItem:
    id: int
    scholar_profile_id: int
    scholar_label: str
    status: str
    reason: str
    dropped_reason: str | None
    attempt_count: int
    resume_cstart: int
    next_attempt_dt: datetime | None
    updated_at: datetime
    last_error: str | None
    last_run_id: int | None


@dataclass(frozen=True)
class QueueClearResult:
    queue_item_id: int
    previous_status: str


class QueueTransitionError(RuntimeError):
    def __init__(self, *, code: str, message: str, current_status: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.current_status = current_status
