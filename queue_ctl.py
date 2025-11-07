from datetime import datetime
from db import get_conn
from model import Job


def enqueue_job(command: str, max_retries: int | None = None) -> Job:
    conn = get_conn()

    if max_retries is None:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM config WHERE key = 'max_retries'")
        row = cursor.fetchone()
        max_retries = int(row["value"]) if row else 3

    job = Job(command=command, max_retries=max_retries)

    job.updated_at = datetime.utcnow().isoformat()

    with conn:
        conn.execute(
            """
            INSERT INTO jobs (id, command, state, attempts, max_retries, created_at, updated_at)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.id,
                job.command,
                job.state,
                job.attempts,
                job.max_retries,
                job.created_at,
                job.updated_at,
            ),
        )

    return job
