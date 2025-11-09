
# QueueCTL

A small CLI-based job queue system implemented in Python. Jobs are persisted in a local SQLite database and processed by background worker processes.

## Demo

You can watch the demo video here:
https://drive.google.com/file/d/1NTKaYDeHbdc--oJwpLifgWlJVrdjbjo7/view?usp=drive_link


## Requirements

- Python 3.10 or newer
- SQLite (bundled with Python)

The project depends on `typer` and `rich`. These dependencies are declared in `pyproject.toml`


## Installation

You can install this tool as a global command (for normal use) or as an editable package (for development).

### For End-Users (Recommended)

This method uses pipx to install the queuectl command globally, making it available everywhere while keeping its dependencies isolated from your system.

1. Clone this repository and navigate into it.

2. Install `pipx` (you only need to do this once):

```bash
pip3 install pipx
pipx ensurepath
```

3. Install `queuectl` from the project directory:

```bash
pipx install .
```

The queuectl command is now globally available.


### For Developers (Editable Install)

This method is for running and developing the code locally.

1. Clone this repository and navigate into it.

2. Create and activate a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

2. Install the package in "editable" mode:

```bash
pip install -e .
```

The queuectl command is now available as long as this virtual environment is active.

## Usage Examples - CLI commands and example outputs

Enqueue a job (prefer single quotes around the JSON to avoid shell escaping):

```bash
# using installed entrypoint
queuectl enqueue '{"command": "echo hello"}'
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

- **CLI (Typer)** - `main.py`: Exposes commands to enqueue jobs, inspect state, start/stop workers, and manage DLQ and config.

- **Queue control** - `queue_ctl.py`: Functions to enqueue jobs, fetch and lock a job for processing, update job state, list jobs, and retry DLQ entries. All DB interactions go through this module.

- **Worker** - `worker.py`: A background worker process that polls for jobs, runs the job command in a subprocess, logs output, and updates job state (completed/failed/dead).
 - **Behaviour**: It uses exponential backoff for retries and honors SIGTERM/SIGINT for graceful shutdown (finishing its current job before exiting). Workers run in detached child processes (via os.fork) and log all activity to /tmp/queuectl_logs/workers.log.

- **Persistence** - An SQLite-backed persistence layer stored at ~/.queuectl/queue.db.
 - **Behaviour**: The application automatically creates the ~/.queuectl directory. It ensures all jobs are durable and stores runtime settings in a key/value config table.

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

## Assumptions & Trade-offs

- **Job Execution:** Jobs are run with subprocess.run(..., shell=True). This is a security trade-off. It provides flexibility (users can run complex shell pipelines) but means that job commands are not sanitized. In a real-world system, this would be a significant security risk (command injection).

- **Concurrency Model:** This project uses a multi-process model (os.fork), which is robust but not cross-platform (it will not work on Windows).

- **Worker Failures:** If a worker is forcibly killed (kill -9) or the machine hard-reboots while a job is processing, that job will remain stuck in the processing state. We implemented a handler to re-queue jobs on SIGTERM, but a hard crash will still orphan the job. This would require a separate "reaper" process to find and requeue stale "processing" jobs.

- **Storage Location:** All data, logs, and PIDs are stored in user-space (~/.queuectl, /tmp/queuectl_logs, /tmp/queuectl_pids). This is portable but not a production-standard location like /var/log or /var/run.

## Testing Instructions

An automated test script is provided in tests/run_tests.py to verify all core functionality. This script uses typer and rich to provide a clean, readable output.

**Prerequisites:**
- Ensure you have installed the project (either via pipx install . or pip install -e .).
- The test script uses Python's built-in sqlite3 module.
- Create and activate a virtual environment and install typer(for looks):

 ```bash
 python3 -m venv venv
 source venv/bin/activate
 pip install typer
 ```

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


## Uninstallation

**If installed with pipx (End-User)**

pipx makes uninstallation simple, but does not remove the app's data.

```
# 1. Uninstall the application
pipx uninstall queuectl-cli

# 2. (Optional) Remove application data and logs
rm -rf ~/.queuectl
rm -rf /tmp/queuectl_logs
rm -rf /tmp/queuectl_pids

```

***If installed with pip (Developer)***

1. Make sure your virtual environment is active (source venv/bin/activate).

2. Uninstall the package:

```
pip uninstall queuectl-cli
```

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

