import subprocess
import time
import signal
from datetime import datetime, timedelta
import queue_ctl
import model
from db import close_conn, load_config
import os

LOG_DIR = "/tmp/queuectl_logs"


def log(worker_id: str, message: str):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)

        log_path = os.path.join(LOG_DIR, "workers.log")
        timestamp = datetime.utcnow().isoformat()

        with open(log_path, "a") as f:
            f.write(f"[{timestamp}] [{worker_id}] {message}\n")

    except Exception as e:
        pass


class Worker:
    def __init__(self, worker_id: str):
        self.worker_id = worker_id

        try:
            self.config = load_config()
        except Exception as e:
            log(worker_id, f"CRITICAL: Failed to load config: {e}")
            self.config = {"max_retries": 3, "backoff_base": 2}

        self.shutdown_flag = False
        log(self.worker_id, "Starting...")
        log(
            self.worker_id,
            f"Config loaded (Max Retries: {self.config['max_retries']}, Backoff: {self.config['backoff_base']})",
        )

    def setup_signal_handlers(self):
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)

    def _handle_shutdown(self, signum, frame):
        log(
            self.worker_id,
            f"Shutdown signal {signum} received. Finishing current job...",
        )
        self.shutdown_flag = True

    def run(self):
        self.setup_signal_handlers()

        try:
            while not self.shutdown_flag:
                try:
                    job = queue_ctl.fetch_job_automatically()

                    if job:
                        log(
                            self.worker_id,
                            f"Picked up job {job.id} (Attempt {job.attempts})",
                        )
                        self.process_job(job)

                    else:
                        log(self.worker_id, "No jobs found. Sleeping...")
                        self.sleep_with_shutdown_check(5)

                except (InterruptedError, OSError) as e:
                    log(
                        self.worker_id,
                        f"Operation interrupted by signal: {e}. Checking shutdown flag.",
                    )
                    continue

        except KeyboardInterrupt:
            log(self.worker_id, "KeyboardInterrupt received. Shutting down...")

        finally:
            log(self.worker_id, "Run loop exiting. Closing database connection.")
            close_conn()

    def sleep_with_shutdown_check(self, duration: int):
        for _ in range(duration):
            if self.shutdown_flag:
                break

            time.sleep(1)

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

            log(self.worker_id, f"Job {job.id} completed.")
            log(self.worker_id, f"Output: {result.stdout.strip()}")
            queue_ctl.update_job_state(job.id, "completed", next_run_time=None)

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            error_output = e.stderr.strip() if hasattr(e, "stderr") else "Timed out"
            log(self.worker_id, f"Job {job.id} failed.")
            log(self.worker_id, f"Error: {error_output}")
            self.handle_failure(job)

        except Exception as e:
            log(
                self.worker_id,
                f"Job {job.id} interrupted by unexpected exception: {e}.",
            )

            if self.shutdown_flag:
                log(self.worker_id, "Interruption was due to shutdown. Re-queuing.")
                queue_ctl.requeue_interrupted_job(job.id, job.attempts)

            else:
                log(self.worker_id, "Interruption was not shutdown. Failing job.")
                self.handle_failure(job)

    def handle_failure(self, job: model.Job):
        if job.attempts >= job.max_retries:
            log(
                self.worker_id,
                f"Job {job.id} has exceeded maximum retries. Moving to DLQ.",
            )
            queue_ctl.update_job_state(job.id, "dead", next_run_time=None)

        else:
            base = self.config["backoff_base"]
            delay_seconds = base**job.attempts

            retry_time = datetime.utcnow() + timedelta(seconds=delay_seconds)
            log(
                self.worker_id,
                f"Job {job.id} failed. Retrying in {delay_seconds}s (at {retry_time.isoformat()}).",
            )
            queue_ctl.update_job_state(
                job.id, "failed", next_run_time=retry_time.isoformat()
            )
