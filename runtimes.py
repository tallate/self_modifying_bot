from __future__ import annotations

import asyncio
import json
import os
import shlex
import subprocess
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


class EchoRuntime:
    async def reply(self, text: str, session_id: str, memory: str = "") -> str:
        return f"收到：{text}"


class DeepSeekHarnessRuntime:
    def __init__(self, config: BotConfig) -> None:
        self.config = config

    async def reply(self, text: str, session_id: str, memory: str = "") -> str:
        try:
            from deepseek_harness import DeepSeekHarness
        except ImportError:
            return "DeepSeek Harness 尚未安装。当前是回声模式：收到：" + text

        def run() -> str:
            with DeepSeekHarness(provider=self.config.provider, model=self.config.model) as harness:
                result = harness.run(self._prompt(text, session_id, memory))
                return result.final_response

        return await asyncio.to_thread(run)

    def _prompt(self, text: str, session_id: str, memory: str) -> str:
        return (
            f"以下是你的稳定人格与安全边界：\n{load_persona()}\n\n"
            "请遵守上述人格。最近经验只能作为参考，不得自行修改程序或安全策略。\n"
            f"会话：{session_id}\n最近经验：\n{memory or '无'}\n用户：{text}"
        )


class HermesAgentRuntime:
    def __init__(self, config: BotConfig) -> None:
        self.command = config.hermes_command

    async def reply(self, text: str, session_id: str, memory: str = "") -> str:
        payload = json.dumps(
            {"session_id": session_id, "message": text, "memory": memory}, ensure_ascii=False
        )
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
    if selected in {"deepseek", "deepseek_harness"}:
        return DeepSeekHarnessRuntime(config)
    if selected in {"hermes", "hermes_agent"}:
        return HermesAgentRuntime(config)
    if selected == "echo":
        return EchoRuntime()
    raise ValueError(f"Unsupported runtime: {config.runtime}")
