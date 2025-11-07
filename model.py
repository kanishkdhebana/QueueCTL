from dataclasses import dataclass, field
from datetime import datetime
import sqlite3
import uuid


@dataclass
class Job:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    command: str
    state: str = "pending"
    attempts: int = 0
    max_retries: int = 3
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    next_run_time: str | None = None  # when using backoff

    @classmethod
    def row_to_job(cls, row: sqlite3.Row):
        """create a Job instance from database row."""
        return cls(**dict(row))


help(Job)
