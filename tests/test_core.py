import hashlib
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from channels import WeChatChannel
from evolution import EvolutionMemory
from jobs import JobStore
from app import is_simple_query
from observability import Telemetry


class WeChatChannelTests(unittest.TestCase):
    def test_signature_and_text_reply(self) -> None:
        channel = WeChatChannel("token")
        signature = hashlib.sha1("".join(sorted(("token", "1", "2"))).encode()).hexdigest()

        self.assertTrue(channel.verify(signature, "1", "2"))
        reply = channel.render_text("user", "account", "a]]>b")
        root = ET.fromstring(reply)
        self.assertEqual(root.findtext("ToUserName"), "user")
        self.assertEqual(root.findtext("FromUserName"), "account")
        self.assertEqual(root.findtext("Content"), "a]]>b")


class EvolutionMemoryTests(unittest.TestCase):
    def test_memory_is_bounded_and_scoped_by_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            memory = EvolutionMemory(Path(directory) / "memory.jsonl", limit=2, enabled=True)
            memory.remember("a", "first", "one")
            memory.remember("b", "other", "two")
            memory.remember("a", "latest", "three")

            self.assertNotIn("first", memory.context("a"))
            self.assertIn("latest", memory.context("a"))
            self.assertNotIn("other", memory.context("a"))


class JobStoreTests(unittest.TestCase):
    def test_enqueue_is_idempotent_and_claim_can_finish(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "state.db")
            first = store.enqueue("msg-1", "session", "user", "hello")
            duplicate = store.enqueue("msg-1", "session", "user", "hello again")
            self.assertEqual(first["id"], duplicate["id"])

            claimed = store.claim("worker-1")
            self.assertIsNotNone(claimed)
            store.finish(claimed["id"], "worker-1", result="done")
            completed = store.find(claimed["id"], "user")
            self.assertEqual(completed["status"], "succeeded")
            self.assertEqual(completed["result"], "done")

    def test_runtime_switch_is_pending_until_applied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "state.db")
            self.assertEqual(store.get_session_runtime("s", "echo"), "echo")
            store.request_runtime("s", "hermes_agent", "echo")
            self.assertEqual(store.get_session_runtime("s", "echo"), "echo")
            self.assertEqual(store.apply_pending_runtime("s"), "hermes_agent")
            self.assertEqual(store.get_session_runtime("s", "echo"), "hermes_agent")


class QueryRoutingTests(unittest.TestCase):
    def test_short_chat_is_sync_candidate_and_long_tool_work_is_async_candidate(self) -> None:
        self.assertTrue(is_simple_query("你好"))
        self.assertFalse(is_simple_query("请分析这个项目并设计测试方案"))


class TelemetryTests(unittest.TestCase):
    def test_finish_preserves_payload_captured_at_event_start(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            telemetry = Telemetry(Path(directory) / "state.db")
            event_id = telemetry.start("trace-1", "model.input", "deepseek", payload="prompt")
            telemetry.finish(event_id)
            event = telemetry.trace("trace-1")[0]
            self.assertEqual(event["attributes"]["payload"], "prompt")

    def test_runtime_tool_events_are_visible_in_trace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            telemetry = Telemetry(Path(directory) / "state.db")
            runtime_event = telemetry.start("trace-2", "runtime.call", "deepseek")
            count = telemetry.record_runtime_events(
                "trace-2",
                [
                    {"type": "tool/call", "data": {"callId": "c1", "name": "cordis_define", "arguments": "{}"}},
                    {"type": "tool/result", "data": {"message": {"source": {"callId": "c1"}, "content": [{"type": "tool-result", "content": [{"type": "text", "text": "defined"}], "isError": False}]}}},
                ],
                runtime_event,
            )
            events = telemetry.trace("trace-2")
            self.assertEqual(count, 2)
            self.assertEqual([event["event_name"] for event in events], ["runtime.call", "tool.call", "tool.result"])
            self.assertEqual(events[1]["attributes"]["tool_name"], "cordis_define")
            self.assertEqual(events[2]["attributes"]["result"], "defined")


if __name__ == "__main__":
    unittest.main()
