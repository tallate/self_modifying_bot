from __future__ import annotations

import hashlib
import time
from typing import Protocol


class Channel(Protocol):
    def verify(self, signature: str, timestamp: str, nonce: str) -> bool: ...

    def render_text(self, to_user: str, from_user: str, content: str) -> str: ...


class WeChatChannel:
    def __init__(self, token: str) -> None:
        self.token = token

    def verify(self, signature: str, timestamp: str, nonce: str) -> bool:
        values = sorted((self.token, timestamp, nonce))
        return hashlib.sha1("".join(values).encode()).hexdigest() == signature

    def render_text(self, to_user: str, from_user: str, content: str) -> str:
        safe_content = content.replace("]]>", "]]]]><![CDATA[>")
        return (
            "<xml>"
            f"<ToUserName><![CDATA[{to_user}]]></ToUserName>"
            f"<FromUserName><![CDATA[{from_user}]]></FromUserName>"
            f"<CreateTime>{int(time.time())}</CreateTime><MsgType><![CDATA[text]]></MsgType>"
            f"<Content><![CDATA[{safe_content}]]></Content></xml>"
        )
