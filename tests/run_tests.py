import typer
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
import subprocess
import sqlite3
import time
import os
import shutil
import sys

app = typer.Typer()
console = Console()

APP_DIR = os.path.join(os.path.expanduser("~"), ".queuectl")
DB_FILE = os.path.join(APP_DIR, "queue.db")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TEST_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "tests/test_output")

LOG_DIR = "/tmp/queuectl_logs"
LOG_FILE = os.path.join(LOG_DIR, "workers.log")
PID_DIR = "/tmp/queuectl_pids"


def info(message):
    console.print(f"[bold blue]> {message}[/bold blue]")


def success(message):
    console.print(f"[bold green]✓ {message}[/bold green]")


def fail(message, stderr=None):
    console.print(
        Panel(
            f"[bold red]✗ {message}[/bold red]", title="Test Failed", border_style="red"
        )
    )
    if stderr:
        console.print("[dim]--- Error Output ---[/dim]")
        console.print(stderr, style="red")
    sys.exit(1)


def run_cli(command: list, check=True):
    result = subprocess.run(["queuectl"] + command, capture_output=True, text=True)

    if check and result.returncode != 0:
        fail(f"CLI command failed: {' '.join(command)}", stderr=result.stderr)
    return result


def get_db_count(state: str) -> int:
    if not os.path.exists(DB_FILE):
        return 0  # DB not created yet
    
    conn = sqlite3.connect(DB_FILE)

    count = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE state = ?", (state,)
    ).fetchone()[0]

    conn.close()
    return count


def assert_db_state(state: str, expected: int):
    info(f"Checking for {expected} job(s) in state '{state}'...")
    count = get_db_count(state)

    if count != expected:
        fail(f"Assertion failed! Expected {expected} '{state}' jobs, found {count}.")

    success(f"Found {count} '{state}' job(s).")


def assert_file_exists(filename: str):
    full_path = os.path.join(TEST_OUTPUT_DIR, filename)
    info(f"Checking for file: {full_path}...")

    if not os.path.exists(full_path):
        fail(f"Assertion failed! File not found: {full_path}")

    success(f"File '{filename}' found.")


def cleanup():
    info("Cleaning up test artifacts...")
    run_cli(["worker", "stop"], check=False)  # Ignore errors if no workers

    if os.path.exists(APP_DIR):
        shutil.rmtree(APP_DIR) # Removes ~/.queuectl
    if os.path.exists(PID_DIR):
        shutil.rmtree(PID_DIR)
    if os.path.exists(LOG_DIR):
        shutil.rmtree(LOG_DIR)
    if os.path.exists(TEST_OUTPUT_DIR):
        shutil.rmtree(TEST_OUTPUT_DIR)

    os.makedirs(APP_DIR, exist_ok=True) 
    os.makedirs(PID_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(TEST_OUTPUT_DIR, exist_ok=True)
    success("Cleanup complete.")


def test_1_success():
    """Tests a basic job completing successfully."""
    console.rule("[bold]Test 1: Basic Job Success[/bold]", style="cyan")
    output_file = "test1.txt"
    run_cli(
        [
            "enqueue",
            f'{{"command": "echo \'test1\' > {TEST_OUTPUT_DIR}/{output_file}"}}',
        ]
    )

    run_cli(["worker", "start", "--count", "1"])
    info("Waiting for worker to complete job (6s)...")
    time.sleep(6)

    assert_db_state("completed", 1)
    assert_file_exists(output_file)
    run_cli(["worker", "stop"])


def test_2_fail_dlq():
    """Tests a failed job retrying and moving to the DLQ."""
    console.rule("[bold]Test 2: Retry and DLQ[/bold]", style="cyan")
    run_cli(["enqueue", '{"command": "exit 1"}'])
    run_cli(["worker", "start", "--count", "1"])
    info("Waiting for job to fail and move to DLQ (approx 10s)...")
    time.sleep(10)  # 2s + 4s + buffer

    assert_db_state("dead", 1)
    run_cli(["worker", "stop"])


def test_3_concurrency():
    """Tests two workers processing jobs in parallel."""
    console.rule("[bold]Test 3: Concurrency[/bold]", style="cyan")
    run_cli(
        ["enqueue", f'{{"command": "sleep 2 && echo A > {TEST_OUTPUT_DIR}/jobA.txt"}}']
    )
    run_cli(
        ["enqueue", f'{{"command": "sleep 2 && echo B > {TEST_OUTPUT_DIR}/jobB.txt"}}']
    )
    run_cli(["worker", "start", "--count", "2"])
    info("Waiting for 2 concurrent jobs to finish (4s)...")
    time.sleep(4)

    assert_db_state("completed", 3)  # 1 from Test 1, 2 from this
    assert_file_exists("jobA.txt")
    assert_file_exists("jobB.txt")
    run_cli(["worker", "stop"])


def test_4_persistence():
    """Tests that a job survives a worker restart."""
    console.rule("[bold]Test 4: Job Data Survives Restart[/bold]", style="cyan")
    output_file = "persist.txt"
    run_cli(
        [
            "enqueue",
            f'{{"command": "echo \'persist\' > {TEST_OUTPUT_DIR}/{output_file}"}}',
        ]
    )

    # This first assertion is the *real* persistence test.
    # It proves the 'enqueue' command successfully saved the job.
    assert_db_state("pending", 1)

    info("Restarting worker to run job (6s)...")
    run_cli(["worker", "start", "--count", "1"])
    time.sleep(6)

    # We check that the job moved from 'pending' to 'completed'.
    # It should be the 4th completed job (1 from T1, 2 from T3)
    assert_db_state("completed", 4)
    assert_file_exists(output_file)
    run_cli(["worker", "stop"])


def test_5_invalid_commands():
    """Tests that the CLI fails gracefully on bad input."""
    console.rule("[bold]Test 5: Invalid Commands Fail Gracefully[/bold]", style="cyan")

    info("Testing 'not json'...")
    res1 = run_cli(["enqueue", "not json"], check=False)

    if res1.returncode == 0:
        fail("Enqueueing 'not json' did not return an error")

    success("'not json' failed as expected.")

    info("Testing 'missing command'...")
    res2 = run_cli(["enqueue", '{"foo": "bar"}'], check=False)

    if res2.returncode == 0:
        fail("Enqueueing job with no 'command' did not return an error")

    success("'missing command' failed as expected.")

    info("Testing 'invalid state'...")
    res3 = run_cli(["list", "--state", "awesome"], check=False)

    if res3.returncode == 0:
        fail("'list --state awesome' did not return an error")

    success("'invalid state' failed as expected.")




@app.command()
def run():
    os.chdir(PROJECT_ROOT)
    start_time = time.time()

    try:
        console.rule("[bold]Starting Test Suite[/bold]", style="blue")
        cleanup()

        test_1_success()
        test_2_fail_dlq()
        test_3_concurrency()
        test_4_persistence()
        test_5_invalid_commands()

    except Exception as e:
        fail(f"A critical test error occurred: {e}")
        
    finally:
        console.rule("[bold]Cleanup[/bold]", style="blue")
        cleanup()

    duration = time.time() - start_time
    console.print(
        Panel(
            f"[bold green]✓ ALL TESTS PASSED[/bold green] (Duration: {duration:.2f}s)",
            title="Test Result",
            expand=False,
        )
    )


if __name__ == "__main__":
    app()