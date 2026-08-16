from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Telemetry:
    """Local trace store for inspecting one bot request end to end."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS trace_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id TEXT NOT NULL,
                    parent_id INTEGER,
                    event_name TEXT NOT NULL,
                    component TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    duration_ms INTEGER,
                    attributes_json TEXT NOT NULL DEFAULT '{}',
                    error_type TEXT,
                    error_message TEXT
                )"""
            )
            connection.execute("CREATE INDEX IF NOT EXISTS trace_events_trace ON trace_events(trace_id, id)")

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def new_trace_id() -> str:
        return f"tr_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def capture(value: Any, limit: int = 12000) -> str:
        """Return a bounded, minimally redacted representation for local traces."""
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
        text = re.sub(r"(?i)(api[_-]?key|authorization|token|password|secret)\s*[:=]\s*[^\s,;]+", r"\1=[REDACTED]", text)
        return text[:limit] + ("…" if len(text) > limit else "")

    def start(self, trace_id: str, event_name: str, component: str, parent_id: int | None = None, **attributes: Any) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT INTO trace_events
                (trace_id, parent_id, event_name, component, status, started_at, attributes_json)
                VALUES (?, ?, ?, ?, 'running', ?, ?)""",
                (trace_id, parent_id, event_name, component, now_iso(), json.dumps(attributes, ensure_ascii=False)),
            )
            return int(cursor.lastrowid)

    def finish(self, event_id: int, status: str = "success", error: BaseException | None = None, **attributes: Any) -> None:
        finished = datetime.now(timezone.utc)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT started_at, attributes_json FROM trace_events WHERE id = ?", (event_id,)
            ).fetchone()
            if row is None:
                return
            started = datetime.fromisoformat(row["started_at"])
            error_type = type(error).__name__ if error else None
            try:
                stored_attributes = json.loads(row["attributes_json"] or "{}")
            except json.JSONDecodeError:
                stored_attributes = {}
            stored_attributes.update(attributes)
            connection.execute(
                """UPDATE trace_events SET status = ?, finished_at = ?, duration_ms = ?,
                attributes_json = ?, error_type = ?, error_message = ? WHERE id = ?""",
                (status, finished.isoformat(), int((finished - started).total_seconds() * 1000),
                 json.dumps(stored_attributes, ensure_ascii=False), error_type, str(error) if error else None, event_id),
            )

    def record_runtime_events(self, trace_id: str, events: list[dict[str, Any]], parent_id: int) -> int:
        """Persist model tool/call and tool/result events emitted by a Harness."""
        calls: dict[str, int] = {}
        recorded = 0
        for event in events:
            event_type = event.get("type")
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            if event_type == "tool/call":
                call_id = str(data.get("callId", ""))
                event_id = self.start(
                    trace_id,
                    "tool.call",
                    "harness",
                    parent_id,
                    call_id=call_id,
                    tool_name=data.get("name", ""),
                    arguments=self.capture(data.get("arguments", "")),
                )
                calls[call_id] = event_id
                self.finish(event_id)
                recorded += 1
            elif event_type == "tool/result":
                message = data.get("message") if isinstance(data.get("message"), dict) else {}
                call_id = str((message.get("source") or {}).get("callId", ""))
                content = message.get("content") if isinstance(message.get("content"), list) else []
                result_text = "\n".join(self._text_values(content)) or self.capture(content)
                attributes = {
                    "call_id": call_id,
                    "result": self.capture(result_text),
                    "is_error": any(
                        isinstance(item, dict) and item.get("isError") for item in content
                    ),
                }
                self.start(trace_id, "tool.result", "harness", calls.get(call_id, parent_id), **attributes)
                recorded += 1
        return recorded

    @staticmethod
    def _text_values(value: Any) -> list[str]:
        if isinstance(value, dict):
            values = [value["text"]] if isinstance(value.get("text"), str) else []
            for child in value.values():
                values.extend(Telemetry._text_values(child))
            return values
        if isinstance(value, list):
            values: list[str] = []
            for child in value:
                values.extend(Telemetry._text_values(child))
            return values
        return []

    def recent_failures(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return [self._decode(dict(row)) for row in connection.execute(
                "SELECT * FROM trace_events WHERE status = 'failure' ORDER BY id DESC LIMIT ?", (limit,)
            )]

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return [self._decode(dict(row)) for row in connection.execute(
                "SELECT * FROM trace_events ORDER BY id DESC LIMIT ?", (limit,)
            )]

    def trace(self, trace_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM trace_events WHERE trace_id = ? ORDER BY id", (trace_id,))
            return [self._decode(dict(row)) for row in rows]

    @staticmethod
    def _decode(event: dict[str, Any]) -> dict[str, Any]:
        try:
            event["attributes"] = json.loads(event.pop("attributes_json"))
        except (KeyError, TypeError, json.JSONDecodeError):
            event["attributes"] = {}
        return event

    def summary(self) -> dict[str, Any]:
        with self._connect() as connection:
            total = connection.execute("SELECT COUNT(*) FROM trace_events").fetchone()[0]
            failures = connection.execute("SELECT COUNT(*) FROM trace_events WHERE status = 'failure'").fetchone()[0]
            running = connection.execute("SELECT COUNT(*) FROM trace_events WHERE status = 'running'").fetchone()[0]
            return {"events": total, "failures": failures, "running": running}
