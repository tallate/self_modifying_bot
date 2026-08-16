from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.isoformat()


class JobStore:
    """Small durable SQLite store for sessions and single-machine jobs."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            yield connection
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    runtime TEXT NOT NULL,
                    pending_runtime TEXT,
                    notification_email TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    source_message_id TEXT UNIQUE NOT NULL,
                    trace_id TEXT,
                    session_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    status TEXT NOT NULL,
                    eta_low INTEGER NOT NULL,
                    eta_high INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    heartbeat_at TEXT,
                    lease_owner TEXT,
                    result TEXT,
                    error TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    lease_until TEXT
                );
                CREATE INDEX IF NOT EXISTS jobs_status_created ON jobs(status, created_at);
                """
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(jobs)")}
            if "lease_owner" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN lease_owner TEXT")
            if "trace_id" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN trace_id TEXT")
            session_columns = {row["name"] for row in connection.execute("PRAGMA table_info(sessions)")}
            if "notification_email" not in session_columns:
                connection.execute("ALTER TABLE sessions ADD COLUMN notification_email TEXT")

    def get_session_runtime(self, session_id: str, default: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT runtime FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if row:
                return row["runtime"]
            connection.execute(
                "INSERT INTO sessions(session_id, runtime, updated_at) VALUES (?, ?, ?)",
                (session_id, default, iso(utc_now())),
            )
            return default

    def request_runtime(self, session_id: str, runtime: str, default: str) -> tuple[str, str | None]:
        current = self.get_session_runtime(session_id, default)
        with self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET pending_runtime = ?, updated_at = ? WHERE session_id = ?",
                (runtime, iso(utc_now()), session_id),
            )
        return current, runtime

    def set_notification_email(self, session_id: str, email: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET notification_email = ?, updated_at = ? WHERE session_id = ?",
                (email, iso(utc_now()), session_id),
            )

    def get_notification_email(self, session_id: str, default: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT notification_email FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            return row["notification_email"] if row and row["notification_email"] else default

    def apply_pending_runtime(self, session_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT pending_runtime FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if not row or not row["pending_runtime"]:
                return None
            runtime = row["pending_runtime"]
            connection.execute(
                "UPDATE sessions SET runtime = ?, pending_runtime = NULL, updated_at = ? WHERE session_id = ?",
                (runtime, iso(utc_now()), session_id),
            )
            return runtime

    def cancel_pending_runtime(self, session_id: str, default: str) -> str:
        current = self.get_session_runtime(session_id, default)
        with self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET pending_runtime = NULL, updated_at = ? WHERE session_id = ?",
                (iso(utc_now()), session_id),
            )
        return current

    def enqueue(self, source_message_id: str, session_id: str, user_id: str, text: str, trace_id: str | None = None) -> sqlite3.Row:
        now = utc_now()
        job_id = f"T-{uuid.uuid4().hex[:8].upper()}"
        with self._connect() as connection:
            try:
                connection.execute(
                    """INSERT INTO jobs
                    (id, source_message_id, trace_id, session_id, user_id, text, status,
                     eta_low, eta_high, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)""",
                    (job_id, source_message_id, trace_id, session_id, user_id, text, 30, 180, iso(now)),
                )
            except sqlite3.IntegrityError:
                pass
            row = connection.execute(
                "SELECT * FROM jobs WHERE source_message_id = ?", (source_message_id,)
            ).fetchone()
            if row is None:
                raise RuntimeError("job was not persisted")
            return row

    def find_recent(self, user_id: str, limit: int = 5) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return list(
                connection.execute(
                    "SELECT * FROM jobs WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                    (user_id, limit),
                )
            )

    def find(self, job_id: str, user_id: str) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute(
                "SELECT * FROM jobs WHERE id = ? AND user_id = ?", (job_id, user_id)
            ).fetchone()

    def claim(self, worker_id: str, lease_seconds: int = 60) -> sqlite3.Row | None:
        now = utc_now()
        lease_until = now + timedelta(seconds=lease_seconds)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """UPDATE jobs SET status = 'queued', lease_owner = NULL, lease_until = NULL
                WHERE status = 'running' AND lease_until < ?""",
                (iso(now),),
            )
            row = connection.execute(
                "SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """UPDATE jobs SET status = 'running', started_at = ?, heartbeat_at = ?,
                lease_owner = ?, lease_until = ?, attempts = attempts + 1 WHERE id = ?""",
                (iso(now), iso(now), worker_id, iso(lease_until), row["id"]),
            )
            return connection.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone()

    def heartbeat(self, job_id: str, worker_id: str, lease_seconds: int = 60) -> None:
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """UPDATE jobs SET heartbeat_at = ?, lease_until = ?
                WHERE id = ? AND status = 'running' AND lease_owner = ?""",
                (iso(now), iso(now + timedelta(seconds=lease_seconds)), job_id, worker_id),
            )

    def finish(self, job_id: str, worker_id: str, result: str | None = None, error: str | None = None) -> None:
        status = "succeeded" if result is not None else "failed"
        with self._connect() as connection:
            connection.execute(
                """UPDATE jobs SET status = ?, result = ?, error = ?, lease_owner = NULL,
                lease_until = NULL WHERE id = ? AND lease_owner = ?""",
                (status, result, error, job_id, worker_id),
            )


def format_job(row: sqlite3.Row) -> str:
    status = row["status"]
    if status == "succeeded":
        return f"任务 {row['id']} 已完成：\n{row['result']}"
    if status == "failed":
        return f"任务 {row['id']} 处理失败：{row['error'] or '未知错误'}"
    return (
        f"任务 {row['id']} 当前状态：{status}\n"
        f"预计还需约 {max(1, row['eta_low'] // 60)}～{max(2, row['eta_high'] // 60)} 分钟。"
    )
