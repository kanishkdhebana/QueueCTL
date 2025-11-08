from dataclasses import dataclass, field
from datetime import datetime, timezone
import sqlite3
import uuid


@dataclass
class Job:
    command: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    state: str = "pending"
    attempts: int = 0
    max_retries: int = 3
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    next_run_time: str | None = None  # when using backoff

    @classmethod
    def row_to_job(cls, row: sqlite3.Row):
        """create a Job instance from database row."""
        return cls(**dict(row))
