import typer
import os
import json
import db
import queue_ctl
from worker import Worker
from typing import Optional
from rich.table import Table
from rich.console import Console

app = typer.Typer(help="queuectl: A CLI-based job queue system.")
worker_app = typer.Typer()
app.add_typer(worker_app, name="worker", help="Manage worker processes.")

console = Console()


@app.callback()
def main():
    db.init_db()


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


@worker_app.command("start")
def worker_start():
    worker_id = f"worker-{os.getpid()}"
    worker = Worker(worker_id)
    worker.run()


if __name__ == "__main__":
    app()
