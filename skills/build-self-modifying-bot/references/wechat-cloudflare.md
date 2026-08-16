# WeChat Official Account with Cloudflare Tunnel

## Public ingress

1. Add the domain to Cloudflare and replace registrar nameservers with the assigned Cloudflare nameservers.
2. Wait until the zone is Active.
3. Create a remotely managed Cloudflare Tunnel.
4. Install `cloudflared` as a service on the machine running the bot. Keep its token secret.
5. Add a Published application route:

```text
Hostname: bot.example.com
Service:  http://localhost:8000
```

6. Require both checks to pass:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod https://bot.example.com/health
```

Do not use a temporary `trycloudflare.com` URL for a persistent webhook.

## WeChat callback

Configure message push with:

```text
URL: https://bot.example.com/wechat
Token: value matching ~/.self_modifying_bot/config.toml or .env
Data format: XML
Encryption: plaintext until AES support is implemented and tested
```

The GET callback must sort Token, timestamp, and nonce, SHA-1 the concatenated value, compare it with `signature`, and return `echostr` as plain text with HTTP 200.

The POST callback must verify the same signature before parsing XML. Return `success` for unsupported message types. Escape CDATA terminators in text replies.

## Response timing

Do not block the callback indefinitely on an agent turn. Apply a short timeout. For slow tasks, acknowledge the webhook and deliver the result through a platform-supported asynchronous reply API when the account has that permission.

## Secret handling

- AppID is an identifier, not a secret.
- AppSecret, EncodingAESKey, API keys, tunnel tokens, passwords, and OTPs are secrets.
- If a secret appears in a screenshot or chat, rotate it before production use.
- Keep WeChat secrets in the channel adapter or secret store; do not pass them into agent prompts.

## Diagnostic order

1. Local `/health`.
2. Public `/health`.
3. Tunnel Healthy status.
4. Exact Token match.
5. Encryption-mode compatibility.
6. Callback HTTP status and Uvicorn logs.
7. Real message delivery from a separate ordinary WeChat user context.
