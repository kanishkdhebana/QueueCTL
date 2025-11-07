import typer
import json
import db
import queue_ctl

app = typer.Typer(help="queuectl: A CLI-based job queue system.")


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
            print("Error: Job JSON must contain a 'command'.")
            raise typer.Exit(code=1)

        job = queue_ctl.enqueue_job(command=command)
        print(f"Job enqueued with ID: {job.id}")

    except json.JSONDecodeError:
        print("Error: Invalid JSON string provided.")
        raise typer.Exit(code=1)

    except Exception as e:
        print(f"An error occurred: {e}")
        raise typer.Exit(code=1)

    finally:
        db.close_conn()


if __name__ == "__main__":
    app()
