"""Логирование и учёт стоимости LLM.

Спека: docs/services/observability.md  (этап M1)
Правило: не логировать секреты и чувствительные персональные данные.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

from app.config import settings

_configured = False
_lock = threading.Lock()


def _ensure_configured() -> None:
    global _configured
    if _configured:
        return
    with _lock:
        if _configured:
            return
        logging.basicConfig(
            level=getattr(logging, settings.log_level.upper(), logging.INFO),
            format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        )
        _configured = True


def get_logger(name: str) -> logging.Logger:
    _ensure_configured()
    return logging.getLogger(name)


@dataclass
class UsageTotals:
    """Агрегированный учёт токенов по моделям (in-process, для контроля OpEx)."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    by_model: dict[str, int] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


usage = UsageTotals()
_usage_logger = get_logger("kabi.llm.usage")


def track_llm_usage(model: str, prompt_tokens: int, completion_tokens: int) -> None:
    """Учёт токенов/стоимости для контроля OpEx (см. observability.md)."""
    usage.prompt_tokens += prompt_tokens
    usage.completion_tokens += completion_tokens
    total = prompt_tokens + completion_tokens
    usage.by_model[model] = usage.by_model.get(model, 0) + total
    _usage_logger.info(
        "llm_usage model=%s prompt=%d completion=%d total_all=%d",
        model,
        prompt_tokens,
        completion_tokens,
        usage.total_tokens,
    )
