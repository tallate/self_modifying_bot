from __future__ import annotations

import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path


class EvolutionMemory:
    """Bounded interaction memory stored outside the source tree."""

    def __init__(self, path: Path, limit: int, enabled: bool) -> None:
        self.path = path
        self.limit = max(1, limit)
        self.enabled = enabled

    def context(self, session_id: str, count: int = 6) -> str:
        if not self.enabled or not self.path.exists():
            return ""
        records = deque(maxlen=count)
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("session_id") == session_id:
                records.append(record)
        return "\n".join(
            f"用户：{record['input']}\n助手：{record['output']}" for record in records
        )

    def remember(self, session_id: str, user_input: str, output: str) -> None:
        if not self.enabled:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existing = deque(maxlen=self.limit - 1 if self.limit > 1 else 0)
        if self.path.exists() and self.limit > 1:
            existing.extend(self.path.read_text(encoding="utf-8").splitlines())
        record = json.dumps(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "session_id": session_id,
                "input": user_input[:4000],
                "output": output[:4000],
            },
            ensure_ascii=False,
        )
        lines = [*existing, record]
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
