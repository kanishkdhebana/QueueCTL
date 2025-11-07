import subprocess
import time
from datetime import datetime, timedelta
import queue_ctl
import model
from db import get_conn, close_conn, load_config


class Worker:
    def __init__(self, worker_id: str):
        self.worker_id = worker_id
        self.config = load_config()
        print(f"Worker {self.worker_id}: Starting...")
        print(
            f"Worker {self.worker_id}: Config loaded (Max Retries: {self.config['max_retries']}, Backoff: {self.config['backoff_base']})"
        )

    def run(self):
        try:
            while True:
                job = queue_ctl.fetch_job_automatically()

                if job:
                    print(f"Worker {self.worker_id}: Picked up job {job.id}")
                    self.process_job(job)

                else:
                    print(f"Worker {self.worker_id}: No jobs found. Sleeping...")
                    time.sleep(5)

        except KeyboardInterrupt:
            print(f"\nWorker {self.worker_id}: Shutting down...")

        finally:
            close_conn()

    def process_job(self, job: model.Job):
        try:
            result = subprocess.run(
                job.command,
                shell=True,
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            )

            print(f"\nWorker {self.worker_id}: Job {job.id} completed.")
            print(f"Output: {result.stdout.strip()}")
            queue_ctl.update_job_state(job.id, "completed", next_run_time=None)

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            error_output = e.stderr.strip() if hasattr(e, "stderr") else "Timed out"
            print(f"\nWorker {self.worker_id}: failed.")
            print(f"\Error {error_output}")
            self.handle_failure(job)

    def handle_failure(self, job: model.Job):
        if job.attempts >= job.max_retries:
            print(
                f"\nWorker {self.worker_id}: Job {job.id} has exceeded maximum retries. Moving to DLQ."
            )
            queue_ctl.update_job_state(job.id, "dead", next_run_time=None)

        else:
            base = self.config["backoff_base"]
            delay_seconds = base**job.attempts

            retry_time = datetime.utcnow() + timedelta(seconds=delay_seconds)
            print(
                f"\nWorker {self.worker_id}: Job {job.id} failed. Retrying in {delay_seconds}s (at {retry_time.isoformat()})."
            )
            queue_ctl.update_job_state(
                job.id, "failed", next_run_time=retry_time.isoformat()
            )
