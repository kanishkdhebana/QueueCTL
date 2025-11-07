import typer
import os
import json
import db
import queue_ctl
import time
import signal
from worker import Worker
from rich.table import Table
from rich.console import Console

app = typer.Typer(help="queuectl: A CLI-based job queue system.")
worker_app = typer.Typer()
app.add_typer(worker_app, name="worker", help="Manage worker processes.")

dlq_app = typer.Typer()
app.add_typer(dlq_app, name="dlq", help="Manage Dead Letter Queue.")

console = Console()

# track running workers
PID_DIR = "/tmp/queuectl_pids"


@app.callback()
def main():
    db.init_db()
    os.makedirs(PID_DIR, exist_ok=True)


@app.command()
def enqueue(
    job_json: str = typer.Argument(
        ..., help='A JSON string defining the job. e.g., \'{"command": "sleep 2"}\''
    ),
):
    try:
        data = json.loads(job_json)
        command = data.get("command")

        if not command:
            console.print("Error: Job JSON must contain a 'command'.")
            raise typer.Exit(code=1)

        job = queue_ctl.enqueue_job(command=command)
        console.print(f"Job enqueued with ID: {job.id}")

    except json.JSONDecodeError:
        console.print("Error: Invalid JSON string provided.")
        raise typer.Exit(code=1)

    except Exception as e:
        console.print(f"An error occurred: {e}")
        raise typer.Exit(code=1)

    finally:
        db.close_conn()


@app.command()
def status():
    try:
        summary = queue_ctl.get_status_summary()

        table = Table(title="Job Queue Status")
        table.add_column("State", style="cyan")
        table.add_column("Count", style="magenta", justify="right")

        for state, count in summary.items():
            table.add_row(state.capitalize(), str(count))

        console.print(table)

    finally:
        db.close_conn()


@app.command("list")
def list_jobs(
    state: str = typer.Option(
        "pending",
        "--state",
        "-s",
        help="Filter jobs by state (pending, processing, completed, failed, dead)",
    ),
):
    try:
        if state not in ("pending", "processing", "completed", "failed", "dead"):
            console.print(f"[bold red]Error: Invalid state '{state}'.[/bold red]")
            raise type.Exit(code=1)

        jobs = queue_ctl.list_jobs_by_state(state)

        table = Table(title=f"{state.capitalize()} Jobs", show_lines=True, expand=True)
        table.add_column("ID", style="cyan")
        table.add_column("Command", style="green")
        table.add_column("Attempts", style="magenta")
        table.add_column("Created At", style="blue")

        for job in jobs:
            table.add_row(job.id, job.command, str(job.attempts), job.created_at)

        console.print(table)

    finally:
        db.close_conn()


@worker_app.command("start")
def worker_start(
    count: int = typer.Option(1, "--count", "-c", help="Number of workers to start."),
):
    console.print(f"Starting {count} worker(s) in the background...")
    for i in range(count):
        pid = os.fork()

        # child process
        if pid == 0:
            # detach from parent's session
            os.setsid()

            dev_null = os.open(os.devnull, os.O_RDWR)
            os.dup2(dev_null, 0)  # stdin
            os.dup2(dev_null, 1)  # stdout
            os.dup2(dev_null, 2)  # stderr
            os.close(dev_null)

            worker_id = f"worker-{os.getpid()}"

            pid_path = os.path.join(PID_DIR, f"{os.getpid()}.pid")
            with open(pid_path, "w") as f:
                f.write(worker_id)

            # close any parent connectin before running worker
            db.close_conn()

            worker = Worker(worker_id)
            worker.run()

            os.remove(pid_path)
            os.exit(0)

        else:
            console.print(f"  > Started worker with PID [bold cyan]{pid}[/bold cyan]")
            time.sleep(0.1)

    console.print("All workers started.")
    db.close_conn()


@worker_app.command("stop")
def worker_stop():
    console.print("Stopping all running workers...")
    stopped_count = 0

    for pid_file in os.listdir(PID_DIR):
        if pid_file.endswith(".pid"):
            pid_path = os.path.join(PID_DIR, pid_file)

            try:
                pid = int(pid_file.replace(".pid", ""))
                os.kill(pid, signal.SIGTERM)

                console.print(
                    f"  > Sent SIGTERM to worker PID [bold cyan]{pid}[/bold cyan]"
                )
                stopped_count += 1

                os.remove(pid_path)

            except ProcessLookupError:
                console.print(
                    f"  > Worker PID [bold cyan]{pid}[/bold cyan] not found. Cleaning up."
                )
                os.remove(pid_path)

            except Exception as e:
                console.print(f"[bold red]Error stopping worker {pid}: {e}[/bold red]")

    if stopped_count == 0:
        console.print("No running workers found.")

    else:
        console.print(f"Stopped {stopped_count} workers.")

    db.close_conn()


@dlq_app.command("list")
def dlq_list():
    list_jobs(state="dead")


@dlq_app.command("retry")
def dlq_retry(job_id: str = typer.Argument(..., help="The ID of the job to retry.")):
    try:
        success = queue_ctl.retry_dead_job(job_id)

        if success:
            console.print(f"Job {job_id} moved back to 'pending'.")

        else:
            console.print(f"[bold red]Error: Job {job_id} not found in DLQ.[/bold red]")

    except Exception as e:
        console.print(f"[bold red]An error occurred: {e}[/bold red]")

    finally:
        db.close_conn()


if __name__ == "__main__":
    app()
