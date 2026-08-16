from __future__ import annotations

import asyncio
import re
import xml.etree.ElementTree as ET
from html import escape

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from channels import WeChatChannel
from config import load_config
from evolution import EvolutionMemory
from jobs import JobStore, format_job
from observability import Telemetry
from runtimes import build_runtime


config = load_config()
wechat = WeChatChannel(config.wechat_token)
runtime = build_runtime(config)
memory = EvolutionMemory(config.memory_path, config.memory_limit, config.evolution_enabled)
jobs = JobStore(config.state_path)
telemetry = Telemetry(config.state_path)
app = FastAPI(title="self_modifying_bot")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10000)
    session_id: str = Field(default="web-anonymous", min_length=1, max_length=120)


class ChatResponse(BaseModel):
    reply: str
    session_id: str


web_origins = [item.strip() for item in config.web_origins.split(",") if item.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=web_origins,
    allow_credentials=False,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "runtime": config.runtime, "model": config.model, **telemetry.summary()}


@app.post("/api/chat", response_model=ChatResponse)
async def web_chat(payload: ChatRequest) -> ChatResponse:
    """网页入口，与微信公众号共用 runtime 和会话记忆。"""
    session_id = payload.session_id.strip() or "web-anonymous"
    text = payload.message.strip()
    runtime_name = jobs.get_session_runtime(session_id, config.runtime)
    trace_id = telemetry.new_trace_id()
    runtime_event = telemetry.start(
        trace_id, "runtime.call", runtime_name, runtime=runtime_name, model=config.model, channel="web"
    )
    selected_runtime = build_runtime(config, runtime_name)
    try:
        reply = await asyncio.wait_for(
            selected_runtime.reply(text, session_id, memory.context(session_id)), timeout=60
        )
    except (TimeoutError, asyncio.TimeoutError) as error:
        telemetry.finish(runtime_event, "failure", error)
        raise HTTPException(status_code=504, detail="机器人响应超时，请稍后重试") from error
    except Exception as error:
        telemetry.finish(runtime_event, "failure", error)
        raise HTTPException(status_code=502, detail="机器人暂时不可用，请稍后重试") from error

    telemetry.finish(runtime_event, output_length=len(reply))
    memory.remember(session_id, text, reply)
    jobs.apply_pending_runtime(session_id)
    return ChatResponse(reply=reply[:12000], session_id=session_id)


@app.get("/api/observability/summary")
async def observability_summary() -> dict:
    return telemetry.summary()


@app.get("/api/observability/failures")
async def observability_failures() -> list[dict]:
    return telemetry.recent_failures()


@app.get("/api/observability/traces")
async def observability_traces() -> list[dict]:
    return telemetry.recent()


@app.get("/api/observability/traces/{trace_id}")
async def observability_trace(trace_id: str) -> list[dict]:
    return telemetry.trace(trace_id)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard() -> str:
    summary = telemetry.summary()
    events = telemetry.recent(30)
    health = "healthy" if summary["failures"] == 0 else "warning"
    health_label = "健康" if health == "healthy" else "需要关注"
    rows = "".join(
        f"<tr><td><a href='/api/observability/traces/{escape(row['trace_id'])}'>{escape(row['trace_id'])}</a></td>"
        f"<td>{escape(row['event_name'])}</td><td>{escape(row['component'])}</td>"
        f"<td><span class='status {escape(row['status'])}'>{escape(row['status'])}</span></td>"
        f"<td>{escape(str(row['duration_ms'] or '—'))} ms</td><td class='error'>{escape(row['error_type'] or '—')}</td></tr>"
        for row in events
    ) or "<tr><td colspan='6' class='empty'>暂无 Trace 事件</td></tr>"
    return f"""<!doctype html>
<html lang='zh-CN'><head><meta charset='utf-8'><meta http-equiv='refresh' content='15'>
<meta name='viewport' content='width=device-width,initial-scale=1'><title>Self Modifying Bot · Operations</title>
<style>
:root {{ --bg:#0b1120; --panel:#111a2e; --panel2:#17223a; --text:#e8eefc; --muted:#8fa1c2; --line:#263554; --blue:#67a4ff; --green:#36d399; --red:#fb7185; --amber:#fbbf24; }}
* {{ box-sizing:border-box }} body {{ margin:0; background:var(--bg); color:var(--text); font:14px/1.5 Inter,Segoe UI,Microsoft YaHei,sans-serif; }}
.layout {{ display:flex; min-height:100vh }} .side {{ width:238px; padding:28px 20px; background:#0d1629; border-right:1px solid var(--line); }}
.brand {{ font-size:18px; font-weight:700; letter-spacing:.2px; }} .brand small {{ display:block; color:var(--muted); font-size:11px; font-weight:400; margin-top:5px; }}
.nav {{ margin-top:42px; color:var(--muted); }} .nav div {{ padding:11px 13px; border-radius:9px; margin:5px 0; }} .nav .active {{ background:#1c3157; color:#fff; }}
.main {{ flex:1; max-width:1500px; padding:34px 42px; }} .top {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:28px; }}
h1 {{ font-size:27px; margin:0 0 4px; }} .subtitle {{ color:var(--muted); }} .refresh {{ color:var(--muted); font-size:12px; }}
.pill {{ border:1px solid #286b57; color:var(--green); background:#123426; border-radius:999px; padding:7px 12px; }}
.grid {{ display:grid; grid-template-columns:repeat(4,minmax(150px,1fr)); gap:16px; }} .card {{ background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:20px; }}
.label {{ color:var(--muted); font-size:12px; }} .value {{ font-size:28px; font-weight:700; margin-top:8px; }} .value small {{ color:var(--muted); font-size:12px; font-weight:400; }}
.section {{ margin-top:26px; }} .section-head {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; }} h2 {{ margin:0; font-size:16px; }}
.runtime {{ display:flex; align-items:center; gap:14px; }} .dot {{ width:10px; height:10px; background:var(--green); border-radius:50%; box-shadow:0 0 12px var(--green); }}
.runtime strong {{ font-size:16px; }} .runtime span {{ color:var(--muted); }} .table-wrap {{ overflow:auto; background:var(--panel); border:1px solid var(--line); border-radius:14px; }}
table {{ width:100%; border-collapse:collapse; min-width:760px; }} th,td {{ padding:13px 16px; text-align:left; border-bottom:1px solid var(--line); }} th {{ color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.05em; }} tr:last-child td {{ border-bottom:0; }}
a {{ color:var(--blue); text-decoration:none; }} .status {{ border-radius:999px; padding:4px 9px; font-size:11px; }} .status.success {{ color:var(--green); background:#123426; }} .status.failure {{ color:var(--red); background:#3a1725; }} .status.running {{ color:var(--amber); background:#3c2d0d; }} .error {{ color:var(--red); }} .empty {{ color:var(--muted); text-align:center; padding:28px; }}
@media(max-width:900px) {{ .side {{ display:none }} .main {{ padding:24px 16px }} .grid {{ grid-template-columns:repeat(2,1fr); }} }}
</style></head><body><div class='layout'>
<aside class='side'><div class='brand'>self_modifying_bot<small>Agent Operations</small></div><div class='nav'><div class='active'>Overview</div><div>Traces</div><div>Failures</div><div>Queue</div><div>Runtimes</div></div></aside>
<main class='main'><div class='top'><div><h1>系统概览</h1><div class='subtitle'>本地可观测性 · 最近事件实时快照</div></div><div><span class='pill'>● {health_label}</span><div class='refresh'>每 15 秒自动刷新</div></div></div>
<div class='grid'><div class='card'><div class='label'>系统状态</div><div class='value' style='color:var(--green)'>在线</div></div><div class='card'><div class='label'>Trace 事件</div><div class='value'>{summary['events']}</div></div><div class='card'><div class='label'>失败事件</div><div class='value' style='color:{'var(--red)' if summary['failures'] else 'var(--green)'}'>{summary['failures']}</div></div><div class='card'><div class='label'>运行中</div><div class='value' style='color:var(--amber)'>{summary['running']}</div></div></div>
<div class='section'><div class='section-head'><h2>当前 Runtime</h2><span class='label'>默认路由</span></div><div class='card runtime'><span class='dot'></span><div><strong>{escape(config.runtime)}</strong><br><span>{escape(config.model)} · {escape(config.provider)}</span></div></div></div>
<div class='section'><div class='section-head'><h2>最近 Trace 事件</h2><a href='/api/observability/traces'>查看 JSON</a></div><div class='table-wrap'><table><tr><th>Trace</th><th>阶段</th><th>组件</th><th>状态</th><th>耗时</th><th>错误</th></tr>{rows}</table></div></div>
</main></div></body></html>"""


@app.get("/wechat", response_class=PlainTextResponse)
async def verify_wechat(
    signature: str = Query(...), timestamp: str = Query(...), nonce: str = Query(...), echostr: str = Query(...)
) -> str:
    if not config.wechat_token or not wechat.verify(signature, timestamp, nonce):
        raise HTTPException(status_code=403, detail="invalid wechat signature")
    return echostr


@app.post("/wechat", response_class=PlainTextResponse)
async def receive_wechat(request: Request) -> str:
    query = request.query_params
    if not wechat.verify(query.get("signature", ""), query.get("timestamp", ""), query.get("nonce", "")):
        raise HTTPException(status_code=403, detail="invalid wechat signature")

    root = ET.fromstring(await request.body())
    message = {child.tag: child.text or "" for child in root}
    if message.get("MsgType") != "text":
        return "success"

    user_id = message.get("FromUserName", "unknown")
    user_text = message.get("Content", "")
    trace_id = telemetry.new_trace_id()
    receive_event = telemetry.start(trace_id, "wechat.receive", "wechat", user_id_hash=hash(user_id), msg_type=message.get("MsgType"))
    source_message_id = message.get("MsgId") or f"{user_id}:{message.get('CreateTime', '')}:{user_text}"
    if user_text.startswith("/harness"):
        telemetry.finish(receive_event, output="command")
        return wechat.render_text(user_id, message.get("ToUserName", ""), harness_command(user_id, user_text))
    if user_text.startswith("/email"):
        telemetry.finish(receive_event, output="email_command")
        return wechat.render_text(user_id, message.get("ToUserName", ""), email_command(user_id, user_text))
    if user_text.startswith("/task") or user_text in {"结果", "任务"}:
        telemetry.finish(receive_event, output="task_status")
        return wechat.render_text(user_id, message.get("ToUserName", ""), task_command(user_id, user_text))

    sync_reply = await try_sync_reply(user_id, user_text)
    if sync_reply is not None:
        telemetry.finish(receive_event, output="sync_reply")
        return wechat.render_text(user_id, message.get("ToUserName", ""), sync_reply)

    notification_email = jobs.get_notification_email(user_id, "")
    if not notification_email:
        telemetry.finish(receive_event, output="email_required")
        return wechat.render_text(
            user_id,
            message.get("ToUserName", ""),
            "这个请求需要后台处理。开始前请先设置结果通知邮箱：\n"
            "/email set your@example.com\n\n设置后请重新发送刚才的问题。",
        )

    queue_event = telemetry.start(trace_id, "queue.enqueue", "queue", receive_event)
    job = jobs.enqueue(source_message_id, user_id, user_id, user_text, trace_id)
    telemetry.finish(queue_event, job_id=job["id"])
    telemetry.finish(receive_event, output="queued", job_id=job["id"])
    reply = (
        f"已开始处理（任务 {job['id']}）。\n"
        "预计约 1～3 分钟完成。当前公众号不支持主动推送，请稍后发送 "
        f"/task {job['id']} 查询结果。"
    )
    return wechat.render_text(user_id, message.get("ToUserName", ""), reply)


def harness_command(session_id: str, text: str) -> str:
    parts = text.split()
    current = jobs.get_session_runtime(session_id, config.runtime)
    if len(parts) == 1 or parts[1] == "status":
        return f"当前 Harness：{current}\n可切换：deepseek_harness、hermes_agent、echo。"
    if parts[1] == "cancel":
        return f"已取消待切换请求，当前 Harness：{jobs.cancel_pending_runtime(session_id, config.runtime)}"
    if parts[1] == "use" and len(parts) == 3:
        target = parts[2]
        if target not in {"deepseek", "deepseek_harness", "hermes", "hermes_agent", "echo"}:
            return "不支持的 Harness。可选：deepseek_harness、hermes_agent、echo。"
        jobs.request_runtime(session_id, target, config.runtime)
        return f"已记录切换到 {target}，将在当前任务完成后生效。"
    return "用法：/harness status、/harness use <name>、/harness cancel"


def email_command(session_id: str, text: str) -> str:
    parts = text.split(maxsplit=2)
    jobs.get_session_runtime(session_id, config.runtime)
    current = jobs.get_notification_email(session_id, "未设置")
    if len(parts) == 1 or parts[1] == "status":
        return f"当前结果接收邮箱：{current}"
    if parts[1] == "set" and len(parts) == 3:
        email = parts[2].strip()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            return "邮箱格式不正确。用法：/email set your@example.com"
        jobs.set_notification_email(session_id, email)
        return f"已设置异步结果接收邮箱：{email}"
    return "用法：/email status、/email set your@example.com"


def task_command(user_id: str, text: str) -> str:
    parts = text.split()
    row = jobs.find(parts[1], user_id) if len(parts) > 1 else None
    if row is None:
        recent = jobs.find_recent(user_id, 1)
        row = recent[0] if recent else None
    return format_job(row) if row else "当前没有找到你的任务。"


def is_simple_query(text: str) -> bool:
    normalized = text.strip().lower()
    complex_markers = (
        "代码", "文件", "分析", "整理", "搜索", "查找", "比较", "总结", "部署",
        "修改", "测试", "运行", "安装", "写一个", "帮我做", "deepseek", "hermes",
        "analyze", "analysis", "project", "design", "test", "code", "file", "search", "summarize",
    )
    return bool(normalized) and len(normalized) <= 160 and not any(
        marker in normalized for marker in complex_markers
    )


async def try_sync_reply(user_id: str, text: str) -> str | None:
    if not is_simple_query(text):
        return None
    runtime_name = jobs.get_session_runtime(user_id, config.runtime)
    trace_id = telemetry.new_trace_id()
    runtime_event = telemetry.start(trace_id, "runtime.call", runtime_name, runtime=runtime_name, model=config.model)
    selected_runtime = build_runtime(config, runtime_name)
    try:
        reply = await asyncio.wait_for(
            selected_runtime.reply(text, user_id, memory.context(user_id)), timeout=4
        )
    except (TimeoutError, asyncio.TimeoutError):
        telemetry.finish(runtime_event, "failure", TimeoutError("runtime timeout"))
        return None
    except Exception as error:
        telemetry.finish(runtime_event, "failure", error)
        return f"当前 Harness 调用失败：{type(error).__name__}。请检查 Harness 配置后重试。"
    telemetry.finish(runtime_event, output_length=len(reply))
    memory.remember(user_id, text, reply)
    jobs.apply_pending_runtime(user_id)
    return reply[:2000]
