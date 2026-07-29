#!/usr/bin/env bash
# Обновить стенд из GitHub (запускать с Mac после git push).
# Usage: ./scripts/deploy_git.sh user1@82.202.137.36
set -euo pipefail

TARGET="${1:-}"
BRANCH="${BRANCH:-main}"
REPO_URL="${REPO_URL:-https://github.com/maksimdor95/kabi.git}"
REMOTE_DIR="${REMOTE_DIR:-~/Kabi}"

if [[ -z "$TARGET" ]]; then
  echo "Usage: $0 user@PUBLIC_IP"
  echo "Сначала: git push origin $BRANCH"
  exit 1
fi

# Локальная страховка: не катим, если есть незапушенные коммиты на этой ветке
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -d "$ROOT/.git" ]]; then
  cd "$ROOT"
  git fetch origin "$BRANCH" 2>/dev/null || true
  LOCAL=$(git rev-parse "$BRANCH" 2>/dev/null || true)
  REMOTE=$(git rev-parse "origin/$BRANCH" 2>/dev/null || true)
  if [[ -n "$LOCAL" && -n "$REMOTE" && "$LOCAL" != "$REMOTE" ]]; then
    echo "ERROR: локальный $BRANCH != origin/$BRANCH. Сделай git push (или pull) сначала."
    exit 1
  fi
  if [[ -n "$(git status --porcelain)" ]]; then
    echo "WARN: есть незакоммиченные файлы. На стенд уйдёт только то, что уже в origin/$BRANCH."
  fi
fi

ssh -o BatchMode=yes "$TARGET" bash -s <<EOF
set -euo pipefail
REMOTE_DIR=$REMOTE_DIR
REPO_URL=$REPO_URL
BRANCH=$BRANCH

if [[ ! -d "\$REMOTE_DIR/.git" ]]; then
  rm -rf "\$REMOTE_DIR"
  git clone --branch "\$BRANCH" "\$REPO_URL" "\$REMOTE_DIR"
else
  cd "\$REMOTE_DIR"
  git fetch origin
  git checkout "\$BRANCH"
  git pull --ff-only origin "\$BRANCH"
fi

cd "\$REMOTE_DIR"
if [[ -d .venv ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip install -q -e .
fi

if systemctl is-enabled kabi-bot >/dev/null 2>&1; then
  sudo systemctl restart kabi-bot
  sudo systemctl is-active kabi-bot
  echo "Логи: journalctl -u kabi-bot -n 20 --no-pager"
fi
EOF

echo "OK → $TARGET:$REMOTE_DIR ($BRANCH from GitHub)"
