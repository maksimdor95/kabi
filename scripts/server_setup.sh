#!/usr/bin/env bash
# Первичная настройка ВМ и запуск инфраструктуры + бота.
# Запускать НА сервере из ~/Kabi: bash scripts/server_setup.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Docker"
if ! command -v docker >/dev/null 2>&1; then
  sudo apt-get update -y
  sudo apt-get install -y docker.io docker-compose-v2 python3.12 python3.12-venv
  sudo usermod -aG docker "$USER" || true
fi

if ! docker info >/dev/null 2>&1; then
  echo "Нет доступа к Docker. Выполни: newgrp docker   или перелогинься по SSH, затем снова:"
  echo "  bash $ROOT/scripts/server_setup.sh"
  exit 1
fi

echo "==> .env"
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Создан .env из .env.example — ЗАПОЛНИ секреты:"
  echo "  nano $ROOT/.env"
  echo "Обязательно: TELEGRAM_BOT_TOKEN, LLM_*, POSTGRES_PASSWORD, APP_ENV=prod"
  echo "Потом снова: bash $ROOT/scripts/server_setup.sh"
  exit 0
fi

if grep -qE '^TELEGRAM_BOT_TOKEN=\s*$' .env || grep -qE '^TELEGRAM_BOT_TOKEN=\s*#' .env; then
  echo "TELEGRAM_BOT_TOKEN пустой в .env — заполни и перезапусти скрипт."
  exit 1
fi

# prod defaults if still local
if grep -q '^APP_ENV=local' .env; then
  sed -i 's/^APP_ENV=local/APP_ENV=prod/' .env
  echo "APP_ENV → prod"
fi

echo "==> Postgres + Redis"
docker compose up -d

echo "==> Python venv"
if [[ ! -d .venv ]]; then
  python3.12 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -U pip
pip install -q -e .

echo "==> systemd unit (kabi-bot)"
SERVICE_FILE=/etc/systemd/system/kabi-bot.service
sudo tee "$SERVICE_FILE" >/dev/null <<EOF
[Unit]
Description=Kabi Telegram bot
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=$USER
WorkingDirectory=$ROOT
Environment=PYTHONPATH=$ROOT
ExecStart=$ROOT/.venv/bin/python -m bot.main
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable kabi-bot
sudo systemctl restart kabi-bot

echo
echo "Готово. Статус:"
sudo systemctl status kabi-bot --no-pager -l || true
echo
echo "Логи: journalctl -u kabi-bot -f"
