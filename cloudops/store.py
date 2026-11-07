"""Additive MySQL persistence; never edits the original example tables."""

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
import pymysql

load_dotenv(Path(__file__).resolve().parents[1] / "agent/.env")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connection():
    conn = pymysql.connect(
        host=os.environ["MYSQL_HOST"],
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        database=os.environ["MYSQL_DATABASE"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
        read_timeout=10,
        write_timeout=10,
    )
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        if conn.open:
            conn.close()


def execute(sql: str, args: tuple = ()) -> int:
    with connection() as conn:
        with conn.cursor() as cur:
            count = cur.execute(sql, args)
        conn.commit()
        return count


def rows(sql: str, args: tuple = ()) -> list[dict]:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            return cur.fetchall()


def initialize() -> None:
    for sql in (
        "CREATE TABLE IF NOT EXISTS ops_demo_resources (id VARCHAR(100) PRIMARY KEY, payload JSON NOT NULL)",
        """CREATE TABLE IF NOT EXISTS ops_tasks (id VARCHAR(36) PRIMARY KEY, environment VARCHAR(20) NOT NULL,
        region VARCHAR(40) NOT NULL, status VARCHAR(30) NOT NULL, active_environment VARCHAR(20) NULL UNIQUE,
        created_at VARCHAR(40) NOT NULL, updated_at VARCHAR(40) NOT NULL, payload JSON NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS ops_steps (id BIGINT PRIMARY KEY AUTO_INCREMENT, task_id VARCHAR(36) NOT NULL,
        payload JSON NOT NULL, INDEX idx_ops_step_task(task_id))""",
        """CREATE TABLE IF NOT EXISTS ops_snapshots (id BIGINT PRIMARY KEY AUTO_INCREMENT, task_id VARCHAR(36) NOT NULL,
        payload JSON NOT NULL, INDEX idx_ops_snapshot_task(task_id))""",
    ):
        execute(sql)


def decode(value):
    return json.loads(value) if isinstance(value, str) else value
