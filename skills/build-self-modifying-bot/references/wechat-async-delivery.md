# WeChat Async Delivery Reference

Use this reference when Agent work may exceed the passive callback response budget or when implementing proactive completion messages.

## Queue selection

| Deployment | Queue |
|---|---|
| One machine, one or a few workers | SQLite with atomic leases |
| Multiple application hosts | Redis-backed queue or a durable broker |
| Strict routing, acknowledgments, and complex delivery topology | RabbitMQ or managed equivalent |
| Existing PostgreSQL deployment | PostgreSQL `FOR UPDATE SKIP LOCKED` is acceptable |

Do not introduce middleware only for fashion. SQLite is durable, inspectable, and operationally simple for a local bot. Do not use in-memory background tasks for work that must survive restart.

## Acceptance reply

Return a passive XML message quickly:

```text
已开始处理（任务 T-8F31）。
预计 1～2 分钟完成，前面还有 1 个任务。
完成后我会在这里发送结果；也可以发送 /task T-8F31 查看进度。
```

If proactive push has not been verified, say:

```text
预计 1～2 分钟完成。当前不能保证主动推送，请稍后发送 /task T-8F31 获取结果。
```

Estimate `queue wait + execution + delivery buffer`. Use historical P50 as the lower bound and P80/P90 as the upper bound for the same runtime, model, and task class. Use conservative cold-start buckets and display rounded ranges.

## Durable job lifecycle

```text
queued → leased → running → succeeded → delivery_pending → delivered
                   └──────→ retry_wait → queued
                   └──────→ failed
```

- Make source message ID unique for callback deduplication.
- Lease jobs atomically with `lease_owner` and `lease_until`.
- Renew the lease with worker heartbeats.
- Requeue expired leases with bounded attempts.
- Check idempotency before retrying side effects.
- Persist results before creating an outbound delivery.

## Customer-service message push

Obtain and cache an `access_token` using AppID and AppSecret, then call:

```http
POST https://api.weixin.qq.com/cgi-bin/message/custom/send?access_token=ACCESS_TOKEN
Content-Type: application/json
```

```json
{
  "touser": "OPENID_FROM_FromUserName",
  "msgtype": "text",
  "text": {"content": "任务 T-8F31 已完成……"}
}
```

Confirm the account exposes the customer-service message permission in its API permissions page. A configured callback URL and enabled AppSecret do not prove outbound permission. Store the exact response `errcode` and `errmsg` from a capability probe.

Treat token expiry as refreshable. Treat account permission failure, canceled subscription, and an expired interaction window as permanent delivery failure. Fall back to `/task <id>` and an optional signed result page.

## Security

- Keep AppSecret in `~/.self_modifying_bot/.env` or a secret store.
- Add the server's outbound public IP to the API IP allowlist when required. A Cloudflare Tunnel hostname is inbound routing, not the outbound IP.
- Do not log access tokens, message plaintext by default, or complete provider responses containing secrets.
- Rotate AppSecret and EncodingAESKey after accidental disclosure.
- Do not let a public WeChat message approve runtime installation, tool permission expansion, or production release.
