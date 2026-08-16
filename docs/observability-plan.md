# self_modifying_bot 方案 1：本地可观测性

## 目标

不依赖 Prometheus、Grafana 或外部 SaaS，仅使用本地 SQLite、JSONL 和内置 Dashboard，查看最近失败、单个 Trace 的完整执行链路以及系统摘要。

## 数据模型

每次微信请求生成一个 `trace_id`。每个阶段写入 `trace_events`：

```text
wechat.receive
  -> router.select_runtime
  -> queue.enqueue / runtime.call
  -> worker.process
  -> harness.call
  -> evolution.update
  -> wechat.reply
```

事件字段包括 `trace_id`、`parent_id`、`event_name`、`component`、`status`、时间、耗时、结构化属性和错误分类。

用户原文、API Key 和完整模型输出不进入观测日志；需要调试时只保存脱敏摘要。

## 接口

- `GET /dashboard`：本地 HTML 看板。
- `GET /api/observability/summary`：事件总数、失败数和运行中事件数。
- `GET /api/observability/failures`：最近失败事件。
- `GET /api/observability/traces/{trace_id}`：单个 Trace 的执行链路。

## 健康判断

第一版不生成复杂的综合评分，而是直接展示：接入、队列、Worker、Runtime、模型、工具和回复阶段的成功/失败状态。这样用户可以先定位根因，再决定是否增加评分。

## 验证标准

一次同步请求应至少出现接收、Runtime 调用和回复事件；一次异步请求应出现接收、入队、Worker 处理、Runtime 调用和回复事件。任何异常都必须在 Trace 中标记为 `failure`，并保存错误类型。

## 异步任务前置条件

异步任务不会在用户未设置通知邮箱时创建。用户需要先发送：

```text
/email set your@example.com
```

设置后，Worker 使用该会话邮箱发送完成或失败通知。普通聊天优先走同步路径；只有明确的复杂关键词、较长请求或同步超时才进入异步候选路径。
