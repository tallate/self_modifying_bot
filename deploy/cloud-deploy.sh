#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/self_modifying_bot}"
REPO_URL="${REPO_URL:-https://github.com/tallate/self_modifying_bot.git}"
BRANCH="${BRANCH:-main}"
CONFIG_DIR="${CONFIG_DIR:-/var/lib/self_modifying_bot}"
BOT_PORT="${BOT_PORT:-8000}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi
command -v git >/dev/null || { echo "git is required" >&2; exit 1; }
command -v docker >/dev/null || { echo "docker is required" >&2; exit 1; }
docker compose version >/dev/null || { echo "Docker Compose plugin is required" >&2; exit 1; }

install -d -m 0750 "$CONFIG_DIR"
if [[ ! -f "$CONFIG_DIR/.env" ]]; then
  install -m 0600 /dev/null "$CONFIG_DIR/.env"
  echo "Created $CONFIG_DIR/.env; add credentials before using a model runtime."
fi

if [[ -d "$APP_DIR/.git" ]]; then
  git -C "$APP_DIR" fetch origin "$BRANCH"
  git -C "$APP_DIR" checkout "$BRANCH"
  git -C "$APP_DIR" reset --hard "origin/$BRANCH"
else
  git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$APP_DIR"
fi

export BOT_CONFIG_DIR="$CONFIG_DIR"
export BOT_PORT
docker compose -f "$APP_DIR/deploy/docker-compose.yml" up -d --build

for attempt in {1..20}; do
  if curl --fail --silent --show-error "http://127.0.0.1:$BOT_PORT/health"; then
    echo
    echo "self_modifying_bot is healthy on 127.0.0.1:$BOT_PORT"
    exit 0
  fi
  sleep 2
done

docker compose -f "$APP_DIR/deploy/docker-compose.yml" ps
docker compose -f "$APP_DIR/deploy/docker-compose.yml" logs --tail 100
exit 1
