from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


CONFIG_HOME = Path(os.getenv("SELF_MODIFYING_BOT_HOME", Path.home() / ".self_modifying_bot"))
CONFIG_PATH = CONFIG_HOME / "config.toml"
ENV_PATH = CONFIG_HOME / ".env"


@dataclass(frozen=True)
class BotConfig:
    wechat_token: str
    runtime: str
    model: str
    provider: str
    deepseek_api_key: str
    deepseek_base_url: str
    hermes_command: str
    evolution_enabled: bool
    memory_path: Path
    memory_limit: int
    state_path: Path
    web_origins: str
    notification_recipient: str
    notification_enabled: bool


def load_config() -> BotConfig:
    CONFIG_HOME.mkdir(parents=True, exist_ok=True)
    load_dotenv(ENV_PATH, override=False)
    data: dict = {}
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("rb") as file:
            data = tomllib.load(file)
    wechat = data.get("wechat", {})
    agent = data.get("agent", {})
    evolution = data.get("evolution", {})
    return BotConfig(
        wechat_token=os.getenv("WECHAT_TOKEN", wechat.get("token", "")),
        runtime=os.getenv("BOT_RUNTIME", agent.get("runtime", "hermes_agent")),
        model=os.getenv("DEEPSEEK_MODEL", agent.get("model", "deepseek-chat")),
        provider=os.getenv("DEEPSEEK_PROVIDER", agent.get("provider", "deepseek-official")),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        hermes_command=os.getenv("HERMES_COMMAND", agent.get("hermes_command", "hermes")),
        evolution_enabled=bool(evolution.get("enabled", True)),
        memory_path=CONFIG_HOME / evolution.get("memory_file", "memory.jsonl"),
        memory_limit=int(evolution.get("memory_limit", 200)),
        state_path=CONFIG_HOME / "state.db",
        web_origins=os.getenv("WEB_ORIGINS", "http://localhost:4000,http://127.0.0.1:4000,https://tallate.github.io"),
        notification_recipient=os.getenv(
            "NOTIFICATION_RECIPIENT", agent.get("notification_recipient", "")
        ),
        notification_enabled=os.getenv(
            "NOTIFICATION_ENABLED", str(agent.get("notification_enabled", True))
        ).lower() == "true",
    )
