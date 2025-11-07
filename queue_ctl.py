from datetime import datetime
from db import get_conn
from model import Job
from typing import List, Dict


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
            WHERE (state = 'pending' OR (state = 'failed' AND next_run_time <= ?))
            ORDER BY created_at
            LIMIT 1
            """,
            (now,),
        )

        row = cursor.fetchone()

        if row is None:
            return None

        job_id = row["id"]

        cursor.execute(
            """
            UPDATE jobs
            SET state = 'processing', updated_at = ?, attempts = attempts + 1
            WHERE id = ? AND (state = 'pending' OR (state = 'failed' AND next_run_time <= ?))
            RETURNING *
            """,
            (now, job_id, now),
        )

        locked_job_row = cursor.fetchone()
        if locked_job_row:
            return Job.row_to_job(locked_job_row)

    return None


def update_job_state(job_id: str, state: str, next_run_time: str | None = None):
    conn = get_conn()
    now = datetime.utcnow().isoformat()
    with conn:
        conn.execute(
            "UPDATE jobs SET state = ?, updated_at = ?, next_run_time = ? WHERE id = ?",
            (state, now, next_run_time, job_id),
        )


def get_status_summary() -> Dict[str, int]:
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT state, count(id) as count
        FROM jobs
        GROUP By state
        """
    )

    rows = cursor.fetchall()

    summary = {
        "pending": 0,
        "processing": 0,
        "completed": 0,
        "failed": 0,
        "dead": 0,
    }

    for row in rows:
        if row["state"] in summary:
            summary[row["state"]] = row["count"]

    return summary


def list_jobs_by_state(state: str) -> List[Job]:
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs WHERE state = ? ORDER BY  created_at", (state,))

    rows = cursor.fetchall()
    return [Job.row_to_job(row) for row in rows]
