---
name: push-notification
description: Send a private task-completion notification through QQ Mail SMTP. Use when the user asks for a push notification, email alert, completion notice, or to be notified after a self_modifying_bot task finishes.
---

# Push Notification

Send an email only after the requested task is genuinely complete and its result is ready.

## Workflow

1. Check the project-local notification configuration:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File ".\skills\push-notification\scripts\send-notification.ps1" -Status
   ```

2. If configuration is missing, run the idempotent initializer. Use `-Force` only to replace the current sender or authorization code.

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File ".\skills\push-notification\scripts\start-push-service.ps1"
   ```

   Prompt locally for the sending mailbox and QQ SMTP authorization code. Store no recipient. Treat setup as incomplete until the status check succeeds. Never ask the user to paste an authorization code into chat.

3. Complete and verify the actual task. Create a short subject and plain-text body containing the outcome, important artifact paths or links, and any remaining caveat.

4. Pass the intended recipient explicitly and send exactly one notification:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File ".\skills\push-notification\scripts\send-notification.ps1" -Recipient "recipient@example.com" -Subject "任务已完成" -Body "任务结果摘要"
   ```

5. Confirm SMTP acceptance from the success output. If sending fails, preserve the task result and report the error.

## Guardrails

- Send only when the user requested notification for the current task or explicitly invokes this skill.
- Pass the intended recipient explicitly with `-Recipient` on every send.
- Keep credentials in the encrypted per-user configuration created by the initializer.
- Keep notification bodies concise and omit secrets, authorization codes, private keys, raw logs, and unnecessary personal information.
- Treat SMTP acceptance as successful sending, not proof that the recipient opened the message.
- Run `-WhatIf` when testing behavior without sending email.
