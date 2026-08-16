# self_modifying_bot 测试计划

> 版本:1.0 · 日期:2026-08-16 · 适用代码基线:app.py / channels.py / runtimes.py / jobs.py / evolution.py / observability.py / worker.py / config.py

## 1. 项目结构与测试范围

- channels.py —— 微信签名验证 + XML 渲染
- runtimes.py —— echo / deepseek_harness / hermes_agent 三种可插拔 Runtime
- evolution.py —— 有界交互记忆(JSONL,按会话隔离)
- jobs.py —— SQLite 任务队列 + 会话状态(runtime 切换、通知邮箱)
- observability.py —— SQLite Trace 事件存储
- worker.py —— 后台消费队列 + 邮件通知(失败不影响任务状态)

**核心链路**:POST /wechat -> 验签 -> 路由(命令/同步/异步入队) -> runtime 调用 -> 回复;
worker 异步:claim -> runtime.reply -> finish -> 邮件通知(失败不影响任务状态)。

**测试目标**:
- 验证每条链路的正确性、边界与失败降级;
- 验证安全边界(签名、XML 注入、任务越权、租约);
- 验证可观测性 Trace 完整性;
- 验证并发与持久化可靠性(幂等、崩溃恢复)。

**不在范围**:真实微信公众号联调(需公网+HTTPS)、DeepSeek/Hermes 真实模型调用(用 echo 或 mock 代替)、PowerShell 邮件脚本本身(用 mock)。

## 2. 分层测试策略

| 层级 | 工具 | 覆盖 |
|---|---|---|
| 单元 | pytest + unittest | channels / runtimes / evolution / jobs / config / app 纯函数 |
| 集成 | fastapi TestClient | 全部 HTTP 端点 + 验签 + 路由 |
| 端到端 | TestClient + 进程内 worker | 入队 -> worker 处理 -> 状态流转 -> 通知 |
| 安全/健壮 | 定向用例 | 畸形输入、越权、并发竞争 |
| 性能 | 基准脚本 | 同步路径延迟、队列吞吐 |

> 注:本仓库依赖 tomllib,运行环境需 Python >= 3.11,或安装 tomli 并提供 shim。

## 3. 测试用例清单

优先级:P0=发布阻塞 P1=重要 P2=常规

### 3.1 channels.py 单元测试

| ID | 场景 | 输入 | 预期 | 优先级 |
|---|---|---|---|---|
| CH-01 | 微信官方签名算法 | token/timestamp/nonce 乱序 | sha1(sort(token,ts,nonce)) 匹配 | P0 |
| CH-02 | 错误签名拒绝 | 篡改 signature | verify 返回 False | P0 |
| CH-03 | 空 token 行为 | token="" | 按 app.py 逻辑应 403 | P0 |
| CH-04 | CDATA 转义 | 内容含 ]]&gt; | 渲染后解析回原文,无 XML 注入 | P0 |
| CH-05 | 内容含 XML 特殊字符 | &lt;tag&gt;&amp;" | 内容原样、XML 合法 | P1 |
| CH-06 | 超长内容(接近截断边界) | 长文本 | 不破坏 XML 结构 | P2 |

### 3.2 runtimes.py 单元测试

| ID | 场景 | 预期 | 优先级 |
|---|---|---|---|
| RT-01 | build_runtime 各别名解析 | deepseek/hermes/echo 及别名 | P0 |
| RT-02 | 非法 runtime 名 | 抛 ValueError | P1 |
| RT-03 | EchoRuntime 回复 | 收到:原文 | P0 |
| RT-04 | DeepSeek 未安装降级 | 返回回声模式提示而非崩溃 | P1 |
| RT-05 | Hermes 命令注入 | hermes_command 含 shell 元字符时 shlex 拆分安全 | P1 |
| RT-06 | Hermes 超时/非零退出 | 异常向上传递,由调用方降级 | P1 |

### 3.3 evolution.py 单元测试

| ID | 场景 | 预期 | 优先级 |
|---|---|---|---|
| EV-01 | 按会话隔离 | A 会话不看到 B 会话记录 | P0 |
| EV-02 | 有界 limit | 超过 limit 丢弃最旧 | P0 |
| EV-03 | 禁用时零写入 | enabled=False 文件不产生 | P0 |
| EV-04 | 损坏 JSON 行 | 跳过坏行不崩溃 | P1 |
| EV-05 | 长输入截断 | input/output 各截 4000 | P1 |
| EV-06 | context count 参数 | 最多返回 count 条 | P2 |
| EV-07 | 并发 remember | 多线程写同一文件不丢记录/不损坏 | P2 |

### 3.4 jobs.py 单元测试

| ID | 场景 | 预期 | 优先级 |
|---|---|---|---|
| JO-01 | enqueue 幂等(微信重试) | 同 source_message_id 返回同一 job | P0 |
| JO-02 | claim->finish 状态流转 | queued->running->succeeded | P0 |
| JO-03 | claim 失败任务 | error 记录,状态 failed | P0 |
| JO-04 | 任务越权隔离 | find(job, 他人 user_id) 返回 None | P0 |
| JO-05 | 租约过期重排队 | running + lease 过期 -> 恢复 queued 可被再 claim | P0 |
| JO-06 | heartbeat 续租 | 续租后 lease_until 更新 | P1 |
| JO-07 | 多 worker 并发 claim | 同一 job 不会被两个 worker 同时拿到 | P0 |
| JO-08 | 会话 runtime 延迟切换 | request->apply 之间仍用旧 runtime | P0 |
| JO-09 | cancel_pending | 取消后 apply 返回 None | P1 |
| JO-10 | 通知邮箱设置/读取/默认值 | set/get/缺省 | P1 |
| JO-11 | 状态机非法流转 | finish 非当前 lease_owner 不生效 | P1 |
| JO-12 | 数据库迁移兼容 | 旧库缺列时自动 ALTER | P2 |

### 3.5 config.py 单元测试

| ID | 场景 | 预期 | 优先级 |
|---|---|---|---|
| CF-01 | 无 config.toml/.env | 使用代码默认值 | P0 |
| CF-02 | env 覆盖 toml | WECHAT_TOKEN 等优先 | P0 |
| CF-03 | 损坏 toml | 明确报错而非静默 | P1 |
| CF-04 | SELF_MODIFYING_BOT_HOME 重定向 | 配置/状态写入指定目录 | P0 |
| CF-05 | memory_limit 非法值(0/负) | 内部 max(1, limit) 钳制 | P2 |

### 3.6 HTTP 集成测试(fastapi TestClient)

| ID | 场景 | 输入 | 预期 | 优先级 |
|---|---|---|---|---|
| AP-01 | GET /wechat 正确签名 | 合法 signature+echostr | 200 回显 echostr | P0 |
| AP-02 | GET /wechat 错误签名 | 篡改 | 403 | P0 |
| AP-03 | GET /wechat 缺参数 | 缺 nonce | 422 | P1 |
| AP-04 | POST /wechat 错误签名 | 篡改 | 403 | P0 |
| AP-05 | POST 畸形 XML | 非 XML 文本 | 当前 500;期望 4xx + failure trace | P0(缺陷) |
| AP-06 | POST 空 body | 空字节 | 当前 500;期望 4xx | P0(缺陷) |
| AP-07 | POST 事件消息 | event/subscribe | 200 success 不回业务 | P0 |
| AP-08 | POST 同步简单文本(echo) | 你好 | 200 XML 回复,含结果 | P0 |
| AP-09 | POST 复杂文本 | 请分析项目并设计测试方案 | 200 入队提示含任务号 | P0 |
| AP-10 | 同步超时降级 | mock runtime 睡眠超 4s | 自动转异步入队 | P0 |
| AP-11 | runtime 调用异常 | mock runtime 抛错 | 200 友好错误文案 | P1 |
| AP-12 | /harness 命令族 | status/use/cancel/非法 | 文案正确、pending 生效 | P1 |
| AP-13 | /email 命令族 | status/set/非法格式 | 文案正确、持久化 | P1 |
| AP-14 | /task 查询 | 有/无任务、他人任务 | 状态/结果文案、越权为空 | P1 |
| AP-15 | /health | - | 200 含 status/runtime/model/telemetry | P0 |
| AP-16 | /dashboard | - | 200 HTML、事件表渲染 | P2 |
| AP-17 | observability API | summary/failures/traces/{id} | JSON 正确、trace 链路完整 | P1 |

### 3.7 端到端 / worker

| ID | 场景 | 预期 | 优先级 |
|---|---|---|---|
| EW-01 | 复杂文本全流程 | POST->入队->worker 消费->succeeded->/task 可查 | P0 |
| EW-02 | 失败任务 | runtime 抛错->failed->/task 显示错误 | P0 |
| EW-03 | 邮件通知失败不影响 | notify 抛错被吞,任务仍 succeeded | P0 |
| EW-04 | 通知开关 | notification_enabled=false 不调用脚本 | P1 |
| EW-05 | worker 崩溃恢复 | 处理中进程被杀->租约过期->重新处理 | P0 |
| EW-06 | 多 worker 并存 | 两个 worker 进程不重复处理 | P1 |
| EW-07 | 异步完成后 runtime 切换生效 | pending_runtime 在完成后应用 | P1 |

### 3.8 安全专项

| ID | 场景 | 预期 | 优先级 |
|---|---|---|---|
| SE-01 | XML 外部实体(XXE) | 不解析外部实体/文件读取 | P0 |
| SE-02 | XML 炸弹(billion laughs) | 不造成资源耗尽(或明确拒绝) | P1 |
| SE-03 | 超大 body | 有大小上限或优雅拒绝 | P1 |
| SE-04 | 命令注入(harness 名/邮箱) | 仅白名单/正则校验 | P0 |
| SE-05 | 用户目录密钥不落源码树 | 配置位于 SELF_MODIFYING_BOT_HOME | P0 |
| SE-06 | Trace 日志脱敏 | 不记录原文/API Key | P1 |

### 3.9 可观测性专项

| ID | 场景 | 预期 | 优先级 |
|---|---|---|---|
| OB-01 | 同步请求 trace 完整性 | receive->runtime.call->reply 至少 3 事件 | P1 |
| OB-02 | 异步请求 trace 完整性 | receive->enqueue->worker.process->runtime.call | P1 |
| OB-03 | 异常标记 failure | 任何异常事件 status=failure + error_type | P1 |
| OB-04 | trace_id 贯穿 | 入队 job.trace_id 与请求一致 | P1 |
| OB-05 | 父事件关联 | worker 事件 parent 指向 enqueue | P2 |

### 3.10 性能/负载(基准)

| ID | 场景 | 预期 | 优先级 |
|---|---|---|---|
| PF-01 | 同步 echo 延迟 | p95 低于 500ms(不含模型) | P2 |
| PF-02 | 入队吞吐 | 100 并发 POST 无 5xx、无重复 job | P1 |
| PF-03 | SQLite 并发 | WAL 下多 worker 无锁死 | P1 |

## 4. 测试环境

- Python >= 3.11(或 3.10 + tomli shim),pytest、httpx(fastapi TestClient)
- 每个测试使用 tempfile 隔离 SELF_MODIFYING_BOT_HOME,不触碰真实用户目录
- 模型调用全部用 EchoRuntime 或 mock,不产生外部依赖
- 邮件通知用 mock/patch,不执行真实 PowerShell

## 5. 已发现的风险点(实测)

| # | 问题 | 位置 | 建议 |
|---|---|---|---|
| 1 | POST /wechat 畸形 XML / 空 body 直接 500,无 trace failure | app.py 110 行附近 | 捕获 ET.ParseError -> 4xx + telemetry.finish(failure) |
| 2 | worker.py PUSH_SCRIPT 硬编码 Windows 路径 | worker.py 17 行附近 | 路径可配置化,非 Windows 环境明确跳过 |
| 3 | telemetry hash(user_id) 受 PYTHONHASHSEED 影响不可复现 | app.py 118 行附近 | 改用稳定 hash(如 sha1 截断) |
| 4 | is_simple_query 关键词表为维护性风险 | app.py 194 行附近 | 抽出配置/常量并补词表测试 |

## 6. 执行与验收

1. 先修复/确认 P0 缺陷(AP-05/AP-06)行为预期;
2. 按 3.1->3.9 顺序执行,全部通过为发布门禁;
3. 关键验收:AP-01/02/04 验签、JO-01 幂等、JO-05 租约、JO-07 并发、EW-01 全流程、OB-01/02 trace 完整性;
4. 回归:现有 tests/test_core.py 5 例保持通过。
