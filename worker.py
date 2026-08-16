from __future__ import annotations

import asyncio
import os
import subprocess
import time
import uuid

from config import load_config
from jobs import JobStore
from observability import Telemetry
from runtimes import build_runtime


PUSH_SCRIPT = r"C:\Users\hgc\.codex\skills\push-notification\scripts\send-notification.ps1"


def notify(config, recipient: str, subject: str, body: str) -> None:
    if not config.notification_enabled or not recipient:
        return
    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                PUSH_SCRIPT,
                "-Recipient",
                recipient,
                "-Subject",
                subject,
                "-Body",
                body[:6000],
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        # Email is an auxiliary delivery channel; the durable Job remains authoritative.
        return


async def run_worker() -> None:
    config = load_config()
    store = JobStore(config.state_path)
    telemetry = Telemetry(config.state_path)
    worker_id = f"worker-{uuid.uuid4().hex[:8]}"
    while True:
        job = store.claim(worker_id)
        if job is None:
            await asyncio.sleep(1)
            continue
        trace_id = job["trace_id"] or telemetry.new_trace_id()
        worker_event = telemetry.start(trace_id, "worker.process", "worker", job_id=job["id"], worker_id=worker_id)
        runtime_name = store.get_session_runtime(job["session_id"], config.runtime)
        runtime = build_runtime(config, runtime_name)
        runtime_event = telemetry.start(trace_id, "runtime.call", runtime_name, worker_event, model=config.model)
        model_input_event = telemetry.start(
            trace_id, "model.input", runtime_name, runtime_event,
            payload=telemetry.capture(f"session={job['session_id']}\n用户：{job['text']}"),
        )
        telemetry.finish(model_input_event)
        try:
            result = await runtime.reply(job["text"], job["session_id"], "")
            model_output_event = telemetry.start(
                trace_id, "model.output", runtime_name, runtime_event,
                payload=telemetry.capture(result), output_length=len(result), tool_events="adapter_not_exposed",
            )
            telemetry.finish(model_output_event)
            telemetry.finish(runtime_event, output_length=len(result), tool_events="adapter_not_exposed")
            store.finish(job["id"], worker_id, result=result)
            telemetry.finish(worker_event, job_id=job["id"])
            store.apply_pending_runtime(job["session_id"])
            recipient = store.get_notification_email(job["session_id"], config.notification_recipient)
            notify(config, recipient, f"Bot 任务 {job['id']} 已完成", f"任务 {job['id']} 已完成。\n\n{result}")
        except Exception as error:
            telemetry.finish(runtime_event, "failure", error)
            telemetry.finish(worker_event, "failure", error, job_id=job["id"])
            store.finish(job["id"], worker_id, error=str(error))
            recipient = store.get_notification_email(job["session_id"], config.notification_recipient)
            notify(config, recipient, f"Bot 任务 {job['id']} 失败", f"任务 {job['id']} 处理失败：\n{error}")


if __name__ == "__main__":
    asyncio.run(run_worker())
