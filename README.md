# self_modifying_bot（自进化 Bot）

微信公众号消息网关和通用 Agent channel。它把微信等消息协议与 Agent runtime 解耦，默认选择 DeepSeek，可切换 Hermes，并为后续自进化能力保留持久化配置和记忆目录。

运行时配置位于用户目录 `%USERPROFILE%\\.self_modifying_bot\\`，项目目录不保存运行时密钥和配置。

## 本地运行

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
New-Item -ItemType Directory -Force "$HOME\\.self_modifying_bot" | Out-Null
Copy-Item config.toml.example "$HOME\\.self_modifying_bot\\config.toml"
Copy-Item .env.example "$HOME\\.self_modifying_bot\\.env"
# 一条命令初始化授权（首次运行）并启动 Web 服务和 Worker
.\restart.ps1
```

Worker 完成任务后会通过已配置的 QQ SMTP 推送邮件到 `notification_recipient`；邮件发送失败不影响 `/task` 查询。可在用户目录配置中关闭：

```toml
[agent]
notification_recipient = "your@example.com"
notification_enabled = true
```

默认 runtime 是 `deepseek_harness`，可在用户目录的 `config.toml` 中改为 `hermes_agent` 或 `echo`。DeepSeek runtime 需要安装并配置对应 Harness/模型凭据；未就绪时会安全回退为回声回复。微信公众号长任务由 `worker.py` 执行，用户通过 `/task <任务号>` 查询结果。

以后可使用 `restart.ps1` 重启本地服务。它会自动检查邮件授权配置；只有首次未配置时才会要求输入 QQ SMTP 授权码：

```powershell
.\restart.ps1
```

首次运行 `restart.ps1` 时会初始化 QQ 邮件推送，交互输入发件邮箱和 SMTP 授权码；凭据保存在 `%USERPROFILE%\.self_modifying_bot\push-notification\`，授权码使用当前 Windows 用户加密。后续启动检测到配置后会直接继续。如需更换发件邮箱或授权码，运行：

```powershell
.\skills\push-notification\scripts\start-push-service.ps1 -Force
```

生产环境请使用 HTTPS 反向代理，并将微信公众号后台的服务器 URL 指向 `/wechat`。

## 配置

非敏感配置保存在 `%USERPROFILE%\\.self_modifying_bot\\config.toml`；API Key 等密钥保存在同目录的 `.env`。默认模型提供方是 `deepseek-official`，模型是 `deepseek-chat`。

自进化能力当前采用有界交互记忆：最近经验写入 `%USERPROFILE%\\.self_modifying_bot\\memory.jsonl` 并提供给后续同一会话。它不会自动修改源代码或安全策略；未来的代码进化应增加独立审批和回滚机制。

## 安全边界

当前版本不会执行用户提供的 shell 命令，也不会把 Codex CLI 直接作为公网 HTTP 服务。需要执行代码或文件任务时，应另加受限的后台 worker、工作目录和人工确认流程。
