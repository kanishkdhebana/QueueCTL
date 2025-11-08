
# QueueCTL

A small CLI-based job queue system implemented in Python. Jobs are persisted in a local SQLite database and processed by background worker processes.


## Requirements

- Python 3.10 or newer
- SQLite (bundled with Python)

The project depends on `typer` and `rich`. These dependencies are declared in `pyproject.toml` and will be installed when you install the package (for example with `pip install -e .`).


## Setup Instructions - Run locally

1. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Ensure the data directory exists (the SQLite file will be created there):

```bash
mkdir -p data
```

3. Install the package and its dependencies (editable install registers the `queuectl` console script):

```bash
pip install -e .
```

After installation the CLI entrypoint `queuectl` will be available (or you can run via `python main.py`).

Note: `main.py` calls `db.init_db()` on startup so the necessary database tables and default config entries will be created automatically when running CLI commands.


## Usage Examples - CLI commands and example outputs

Note: the project exposes a Typer-based CLI. You can use the installed `queuectl` command or call `python main.py`.

Enqueue a job (prefer single quotes around the JSON to avoid shell escaping):

```bash
# using installed entrypoint
queuectl enqueue '{"command": "echo hello"}'

# or with python
python main.py enqueue '{"command": "echo hello"}'
```

Example output:

```
Job enqueued with ID: 8f14e45f-cea3-4a2f-9e4b-1a2b3c4d5e6f
```

Show status summary:

```bash
queuectl status
```

List jobs (filter by state):

```bash
# list pending jobs
queuectl list --state pending
```

Start worker(s) in background (the CLI forks processes, detaches, and writes PID files to `/tmp/queuectl_pids`):

```bash
queuectl worker start --count 1
```

The CLI will print the PID of started worker(s). Workers write activity to `/tmp/queuectl_logs/workers.log` by default.

Stop workers (reads PID files from `/tmp/queuectl_pids` and sends SIGTERM):

```bash
queuectl worker stop
```

Dead-letter queue (DLQ) management:

```bash
# list dead jobs
queuectl dlq list

# retry a job from DLQ (puts it back to pending)
queuectl dlq retry <job-id>
```

Configuration (keys: `max_retries`, `backoff_base`):

```bash
queuectl config list
queuectl config set max_retries 5
```

## Architecture Overview

High-level components:

- CLI (Typer) - `main.py`: exposes commands to enqueue jobs, inspect state, start/stop workers, and manage DLQ and config. `main.py` also ensures the DB and runtime directories exist.
- Queue control - `queue_ctl.py`: functions to enqueue jobs, fetch and lock a job for processing, update job state, list jobs, and retry DLQ entries. All DB interactions go through this module.
- Worker - `worker.py`: background worker process that polls for jobs, runs the job command in a subprocess, logs output, and updates job state (completed/failed/dead). It uses exponential backoff between retries and honors SIGTERM/SIGINT for graceful shutdown.
- Persistence - `db.py`: an SQLite-backed persistence layer stored at `data/queue.db`. It also stores configuration in a simple key/value `config` table and provides helpers to initialize and load config.

Job lifecycle:

1. Enqueued with state `pending` and stored in the `jobs` table.
2. A worker calls `fetch_job_automatically()` which selects one eligible job (state = `pending`, or `failed` with `next_run_time` <= now), updates it to `processing` and increments `attempts` in the same transaction, then returns the locked job.
3. The worker runs the job `command` using `subprocess.run(shell=True)`:
   - On success: job state -> `completed`.
   - On failure or timeout: if attempts >= max_retries -> job state -> `dead` (DLQ). Otherwise job state -> `failed` and `next_run_time` is set using exponential backoff (backoff_base ** attempts).
4. DLQ entries can be retried via `queuectl dlq retry <id>` which sets them back to `pending` and resets attempts.

Data model (important fields in `jobs` table):

- `id`: UUID string primary key
- `command`: shell command string to execute
- `state`: one of `pending`, `processing`, `completed`, `failed`, `dead`
- `attempts`: number of attempts made
- `max_retries`: per-job maximum retries
- `created_at`, `updated_at`, `next_run_time` (for backoff)

Worker behavior details:

- Workers run in detached child processes when started via `queuectl worker start` (PID files are created under `/tmp/queuectl_pids`).
- Workers log runtime events to `/tmp/queuectl_logs/workers.log`.
- Graceful shutdown: workers handle SIGTERM/SIGINT, set a shutdown flag, and attempt to finish the current job before exiting.



## Assumptions & Trade-offs

- Persistence: SQLite is used for simplicity and local development. This is not designed for high-concurrency production loads.

- Locking & concurrency: `fetch_job_automatically()` relies on selecting a candidate job then using `UPDATE ... RETURNING` to atomically claim it. That pattern depends on SQLite features and is sufficient for light local concurrency, but for heavier loads or distributed workers consider Postgres, Redis, or an external job service.

- Background workers: the CLI's fork-and-detach approach is simple and convenient for demos. For production you should use a process manager (systemd, supervisord) or container orchestration.

- Security: job commands are executed with `shell=True`. Do not enqueue untrusted commands in production.

## Checklist

- [x] All required commands functional
- [x] Jobs persist after restart
- [x] Retry and backoff implemented correctly
- [x] DLQ operational
- [x] CLI user-friendly and documented
- [-] Code is modular and maintainable
- [ ] Includes test or script verifying main flows


## Contact / Maintainers

This repository was created as a compact demo project. For changes, run tests and follow the code style already present in the repo.

