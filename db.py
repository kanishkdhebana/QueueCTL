import sqlite3
import threading

DB_PATH = "data/queue.db"

_local = threading.local()


def get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)

    if conn is None:
        conn = sqlite3.connect(DB_PATH)

        # query results are accessible by column name instead of index
        conn.row_factory = sqlite3.Row
        _local.conn = conn

    return conn


def init_db():
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs(
        id TEXT PRIMARY KEY,
        command TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0,
        max_retries INTEGER NOT NULL DEFAULT 3,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        next_run_time TEXT -- for exponential backoff
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS config(
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    cursor.execute(
        "INSERT OR IGNORE INTO config (key, value) VALUES('max_retries', '3')"
    )
    cursor.execute(
        "INSERT OR IGNORE INTO config (key, value) VALUES('backoff_base', '2')"
    )

    conn.commit()


def close_conn():
    conn = getattr(_local, "conn", None)

    if conn is not None:
        conn.close()
        _local.conn = None


def load_config() -> dict:
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM config")
    config = {row["key"]: row["value"] for row in cursor.fetchall()}

    config["max_retries"] = int(config["max_retries"])
    config["backoff_base"] = int(config["backoff_base"])
    return config


def update_config(key: str, value: str):
    conn = get_conn()
    with conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES(?, ?)", (key, value)
        )
