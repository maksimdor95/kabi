"""Краткосрочная память диалога (windowed history) для M9.

Спека: docs/services/dialogue-agent.md
Хранилище: Redis list; при недоступности Redis — процессный fallback (тесты/local).
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.config import settings
from app.observability.logging import get_logger

logger = get_logger("kabi.dialog_memory")

WINDOW = 12  # последних сообщений (user+assistant вместе)
TTL_SECONDS = 60 * 60 * 24 * 7  # 7 дней

_mem: dict[str, list[dict[str, str]]] = {}
_redis: Any = None
_redis_failed = False


def _key(user_id: UUID) -> str:
    return f"kabi:dialog:{user_id}"


async def _client() -> Any | None:
    """Ленивый Redis; None если недоступен."""
    global _redis, _redis_failed
    if _redis_failed:
        return None
    if _redis is not None:
        return _redis
    try:
        from redis.asyncio import Redis

        client = Redis.from_url(settings.redis_url, decode_responses=True)
        await client.ping()
        _redis = client
        return _redis
    except Exception as exc:  # noqa: BLE001 — fallback осознанный
        logger.warning("dialog_memory: Redis недоступен, in-memory fallback: %s", exc)
        _redis_failed = True
        return None


async def get_history(user_id: UUID) -> list[dict[str, str]]:
    """Вернуть окно истории: [{role, content}, ...]."""
    key = _key(user_id)
    client = await _client()
    if client is None:
        return list(_mem.get(key, []))
    try:
        raw = await client.lrange(key, 0, WINDOW - 1)
        out: list[dict[str, str]] = []
        for item in raw:
            try:
                msg = json.loads(item)
            except json.JSONDecodeError:
                continue
            role = str(msg.get("role") or "")
            content = str(msg.get("content") or "")
            if role in ("user", "assistant") and content:
                out.append({"role": role, "content": content})
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("dialog_memory get failed: %s", exc)
        return list(_mem.get(key, []))


async def append_turn(user_id: UUID, user_text: str, assistant_text: str) -> None:
    """Добавить пару user/assistant и обрезать окно."""
    key = _key(user_id)
    turns = [
        {"role": "user", "content": user_text.strip()},
        {"role": "assistant", "content": assistant_text.strip()},
    ]
    turns = [t for t in turns if t["content"]]

    client = await _client()
    if client is None:
        hist = _mem.setdefault(key, [])
        hist.extend(turns)
        del hist[:-WINDOW]
        return

    try:
        pipe = client.pipeline()
        for t in turns:
            pipe.rpush(key, json.dumps(t, ensure_ascii=False))
        pipe.ltrim(key, -WINDOW, -1)
        pipe.expire(key, TTL_SECONDS)
        await pipe.execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("dialog_memory append failed: %s", exc)
        hist = _mem.setdefault(key, [])
        hist.extend(turns)
        del hist[:-WINDOW]


async def clear(user_id: UUID) -> None:
    """Сбросить историю (рестарт онбординга /delete)."""
    key = _key(user_id)
    _mem.pop(key, None)
    client = await _client()
    if client is None:
        return
    try:
        await client.delete(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("dialog_memory clear failed: %s", exc)


def reset_for_tests() -> None:
    """Сброс процессного кэша и флага Redis (только тесты)."""
    global _redis, _redis_failed
    _mem.clear()
    _redis = None
    _redis_failed = False
