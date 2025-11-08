
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

### High-level components:

- **CLI (Typer)** - `main.py`: exposes commands to enqueue jobs, inspect state, start/stop workers, and manage DLQ and config. `main.py` also ensures the DB and runtime directories exist.
- **Queue control** - `queue_ctl.py`: functions to enqueue jobs, fetch and lock a job for processing, update job state, list jobs, and retry DLQ entries. All DB interactions go through this module.
- **Worker** - `worker.py`: background worker process that polls for jobs, runs the job command in a subprocess, logs output, and updates job state (completed/failed/dead). It uses exponential backoff between retries and honors SIGTERM/SIGINT for graceful shutdown.
- **Persistence** - `db.py`: an SQLite-backed persistence layer stored at `data/queue.db`. It also stores configuration in a simple key/value `config` table and provides helpers to initialize and load config.

### Job lifecycle:

1. Enqueued with state `pending` and stored in the `jobs` table.
2. A worker calls `fetch_job_atomically` which selects one eligible job (state = `pending`, or `failed` with `next_run_time` <= now), updates it to `processing` and increments `attempts` in the same transaction, then returns the locked job.
3. The worker runs the job `command` using `subprocess.run(shell=True)`:
   - On success: job state -> `completed`.
   - On failure or timeout: if attempts >= max_retries -> job state -> `dead` (DLQ). Otherwise job state -> `failed` and `next_run_time` is set using exponential backoff (backoff_base ** attempts).
4. DLQ entries can be retried via `queuectl dlq retry <id>` which sets them back to `pending` and resets attempts.

### Data model (important fields in `jobs` table):

- `id`: UUID string primary key
- `command`: shell command string to execute
- `state`: one of `pending`, `processing`, `completed`, `failed`, `dead`
- `attempts`: number of attempts made
- `max_retries`: per-job maximum retries
- `created_at`, `updated_at`, `next_run_time` (for backoff)

### Data Persistence

The system uses a single SQLite database file (data/queue.db) to store all state. This includes:

- The jobs table (stores all jobs and their state).

- The config table (a key-value store for settings).

This ensures that all enqueued jobs are durable and will survive application or system restarts.

### Worker behavior details:

- Workers run in detached child processes when started via `queuectl worker start` (PID files are created under `/tmp/queuectl_pids`).
- Workers log runtime events to `/tmp/queuectl_logs/workers.log`.
- Graceful shutdown: workers handle SIGTERM/SIGINT, set a shutdown flag, and attempt to finish the current job before exiting.



## Assumptions & Trade-offs

- **Job Execution:** Jobs are run with subprocess.run(..., shell=True). This is a security trade-off. It provides flexibility (users can run complex shell pipelines) but means that job commands are not sanitized. In a real-world system, this would be a significant security risk (command injection).

- **Concurrency Model:** This project uses a multi-process model (os.fork), which is robust but not cross-platform (it will not work on Windows).

- **Worker Failures:** If a worker is forcibly killed (kill -9) or the machine hard-reboots while a job is processing, that job will remain stuck in the processing state. We implemented a handler to re-queue jobs on SIGTERM, but a hard crash will still orphan the job. This would require a separate "reaper" process to find and requeue stale "processing" jobs.

- **Logging:** Worker logs are sent to /tmp/queuectl_logs/workers.log and are not automatically rotated or size-limited.

## Testing Instructions

An automated test script is provided in `tests/run_tests.py` to verify all core functionality.

Prerequisites:
- Ensure you have installed the project via pip install -e ..
- The script requires the sqlite3 command-line tool (typically pre-installed on Linux/macOS).

To run the tests:
```
python tests/run_tests.py
```

The script will automatically:

1. Clean up any old state (database, PID files, logs).

2.  Run a series of tests for the 5 key scenarios.

3. Provide clear, color-coded "PASS" or "FAIL" output.

4. Clean up all test artifacts when finished.

 ### Test Scenarios Covered:

- **Test 1: Basic Job Success:** Verifies a job can be enqueued, completed, and its output file created.

- **Test 2: Retry and DLQ:** Verifies a failing job retries and correctly moves to the dead state.

- **Test 3: Concurrency:** Verifies two workers can process jobs in parallel.

- **Test 4: Job Data Survives Restart:** Verifies a pending job is not lost and is processed by a new worker.

- **Test 5: Invalid Commands:** Verifies the CLI gracefully rejects malformed input.

## Checklist

- [x] All required commands functional
- [x] Jobs persist after restart
- [x] Retry and backoff implemented correctly
- [x] DLQ operational
- [x] CLI user-friendly and documented
- [x] Code is modular and maintainable
- [x] Includes test or script verifying main flows


## Contact / Maintainers

This repository was created as a compact demo project. For changes, run tests and follow the code style already present in the repo.

