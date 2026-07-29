#!/usr/bin/env bash
# DEPRECATED для обычного деплоя. Используй scripts/deploy_git.sh после git push.
# Оставлен только для аварийного bootstrap без Git на ВМ.
# Usage: ./scripts/deploy_rsync.sh user1@1.2.3.4
set -euo pipefail

echo "WARN: предпочитай ./scripts/deploy_git.sh (см. .cursor/rules/deploy-via-git.mdc)" >&2

TARGET="${1:-}"
if [[ -z "$TARGET" ]]; then
  echo "Usage: $0 user@PUBLIC_IP"
  echo "Example: $0 user1@203.0.113.10"
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE_DIR="${REMOTE_DIR:-~/Kabi}"

rsync -avz --delete \
  --exclude '.venv/' \
  --exclude '.git/' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude '.mypy_cache/' \
  --exclude '.ruff_cache/' \
  --exclude '.env' \
  --exclude '*.pyc' \
  --exclude '.DS_Store' \
  "$ROOT/" "$TARGET:$REMOTE_DIR/"

echo
echo "OK → $TARGET:$REMOTE_DIR"
echo "Дальше на сервере:"
echo "  ssh $TARGET"
echo "  bash ~/Kabi/scripts/server_setup.sh"
