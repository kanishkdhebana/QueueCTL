import subprocess
import time
import queue_ctl
import model
from db import close_conn


class Worker:
    def __init__(self, worker_id: str):
        self.worker_id = worker_id
        print(f"Worker {self.worker_id}: Starting...")

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
            queue_ctl.update_job_state(job.id, "completed")

        except subprocess.CalledProcessError as e:
            print(f"\nWorker {self.worker_id}: failed.")
            print(f"\Error {e.stderr.strip()}")
            queue_ctl.update_job_state(job.id, "failed")

        except subprocess.TimeoutExpired:
            print(f"\nWorker {self.worker_id}: timed out.")
            queue_ctl.update_job_state(job.id, "failed")
