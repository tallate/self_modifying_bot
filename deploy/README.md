# 云端部署

部署目标是单台 Alibaba Cloud ECS，通过 Workbench 进入服务器后执行：

```bash
git clone https://github.com/tallate/self_modifying_bot.git /opt/self_modifying_bot
cd /opt/self_modifying_bot
chmod +x deploy/cloud-deploy.sh
deploy/cloud-deploy.sh
```

首次部署后编辑 `/var/lib/self_modifying_bot/.env`，至少设置：

```dotenv
BOT_RUNTIME=echo
```

如果使用 DeepSeek，再设置 `DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL` 和 `DEEPSEEK_API_KEY`。配置目录独立于代码目录，并由 Docker volume 持久化。

## 反向代理

容器只绑定 `127.0.0.1:8000`。生产环境应由 Cloudflare Tunnel、Nginx 或 Caddy 终止 HTTPS，再转发到 `http://127.0.0.1:8000`。

微信公众号服务器 URL 使用 `https://bot.antseek.xyz/wechat`。

## 验证

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS -X POST http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"cloud-test","message":"你好"}'
docker compose -f /opt/self_modifying_bot/deploy/docker-compose.yml ps
```
