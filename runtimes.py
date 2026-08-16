from __future__ import annotations

import asyncio
import json
import os
import shlex
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Protocol

from config import BotConfig


PERSONA_PATH = Path(__file__).with_name("PERSONA.md")


def load_persona() -> str:
    try:
        return PERSONA_PATH.read_text(encoding="utf-8")
    except OSError:
        return "你是 self_modifying_bot 的默认 DeepSeek Agent。"


class AgentRuntime(Protocol):
    async def reply(self, text: str, session_id: str, memory: str = "") -> str: ...


class RuntimeBusyError(RuntimeError):
    """Raised when a session already has an active Harness turn."""


class RuntimeEmptyResponseError(RuntimeError):
    """Raised when a Harness completes without a user-facing response."""


class EchoRuntime:
    async def reply(self, text: str, session_id: str, memory: str = "") -> str:
        return f"收到：{text}"


class DeepSeekHarnessRuntime:
    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self._harness = None
        self._sessions = {}
        self._session_locks = {}
        self._process_session_prefix = uuid.uuid4().hex[:12]
        self.last_events = []
        self.last_input = ""

    def _session(self, session_id: str):
        from deepseek_harness import DeepSeekHarness

        if self._harness is None:
            self._harness = DeepSeekHarness(
                provider=self.config.provider,
                model=self.config.model,
                base_url=self.config.deepseek_base_url,
                api_key=self.config.deepseek_api_key or None,
            )
        if session_id not in self._sessions:
            harness_session_id = f"bot-{self._process_session_prefix}-{uuid.uuid5(uuid.NAMESPACE_URL, session_id).hex[:16]}"
            self._sessions[session_id] = self._harness.start_session(harness_session_id)
        return self._sessions[session_id]

    def _lock_for(self, session_id: str) -> threading.Lock:
        if session_id not in self._session_locks:
            self._session_locks[session_id] = threading.Lock()
        return self._session_locks[session_id]

    async def reply(self, text: str, session_id: str, memory: str = "") -> str:
        try:
            from deepseek_harness import DeepSeekHarness  # noqa: F401
        except ImportError:
            return "DeepSeek Harness 尚未安装。当前是回声模式：收到：" + text

        def run() -> str:
            prompt = self._prompt(text, session_id, memory)
            self.last_input = prompt
            lock = self._lock_for(session_id)
            if not lock.acquire(blocking=False):
                raise RuntimeBusyError(f"session {session_id} already has an active Harness turn")
            try:
                result = self._session(session_id).run(prompt)
                self.last_events = result.events
                if result.finish_reason == "error":
                    raise RuntimeError(self._last_runtime_error(result.events))
                if not result.final_response.strip():
                    raise RuntimeEmptyResponseError("Harness completed without a final response")
                return result.final_response
            finally:
                lock.release()

        return await asyncio.to_thread(run)

    def close(self) -> None:
        if self._harness is not None:
            harness = self._harness
            self._harness = None
            self._sessions.clear()
            self._session_locks.clear()
            self._process_session_prefix = uuid.uuid4().hex[:12]
            try:
                harness.close()
            except Exception:
                # A timed-out SDK turn may already have torn down its child process.
                pass

    @staticmethod
    def _last_runtime_error(events: list[dict]) -> str:
        for event in reversed(events):
            if event.get("type") not in {"turn/end", "assistant/chunk"}:
                continue
            text = str(event.get("data", {}))
            if text:
                return text[:1000]
        return "Harness returned an error finish reason"

    def _prompt(self, text: str, session_id: str, memory: str) -> str:
        return (
            f"以下是你的稳定人格与安全边界：\n{load_persona()}\n\n"
            "请遵守上述人格。最近经验只能作为参考，不得自行修改程序或安全策略。\n"
            f"会话：{session_id}\n最近经验：\n{memory or '无'}\n用户：{text}"
        )


class HermesAgentRuntime:
    def __init__(self, config: BotConfig) -> None:
        self.command = config.hermes_command
        self.last_input = ""
        self.last_events = []

    async def reply(self, text: str, session_id: str, memory: str = "") -> str:
        payload = json.dumps(
            {"session_id": session_id, "message": text, "memory": memory}, ensure_ascii=False
        )
        self.last_input = payload
        command = shlex.split(self.command)

        def run() -> str:
            result = subprocess.run(
                [*command, "run", "--json"],
                input=payload,
                capture_output=True,
                text=True,
                check=True,
                timeout=120,
                env=os.environ.copy(),
            )
            return result.stdout.strip()

        return await asyncio.to_thread(run)


def build_runtime(config: BotConfig, runtime_name: str | None = None) -> AgentRuntime:
    selected = runtime_name or config.runtime
    cache_key = (id(config), selected)
    cached = _RUNTIME_CACHE.get(cache_key)
    if cached is not None:
        return cached
    if selected in {"deepseek", "deepseek_harness"}:
        instance = DeepSeekHarnessRuntime(config)
    elif selected in {"hermes", "hermes_agent"}:
        instance = HermesAgentRuntime(config)
    elif selected == "echo":
        instance = EchoRuntime()
    else:
        raise ValueError(f"Unsupported runtime: {selected}")
    _RUNTIME_CACHE[cache_key] = instance
    return instance


_RUNTIME_CACHE: dict[tuple[int, str], AgentRuntime] = {}
