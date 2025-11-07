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


def fetch_job_automatically() -> Job | None:
    conn = get_conn()
    now = datetime.utcnow().isoformat()

    with conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id FROM jobs
            WHERE state = 'pending'
            ORDER BY created_at
            LIMIT 1
            """
        )

        row = cursor.fetchone()

        if row is None:
            return None

        job_id = row["id"]

        cursor.execute(
            """
            UPDATE jobs
            SET state = 'processing', updated_at = ?, attempts = attempts + 1
            WHERE id = ? AND state = 'pending'
            RETURNING *
            """,
            (now, job_id),
        )

        locked_job_row = cursor.fetchone()
        if locked_job_row:
            return Job.row_to_job(locked_job_row)

    return None


def update_job_state(job_id: str, state: str):
    conn = get_conn()
    now = datetime.utcnow().isoformat()
    with conn:
        conn.execute(
            "UPDATE jobs SET state = ?, updated_at = ? WHERE id = ?",
            (state, now, job_id),
        )
