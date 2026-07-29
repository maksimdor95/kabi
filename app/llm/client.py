"""Клиент LLM с роутингом моделей (primary/cheap) и эмбеддингами.

Провайдер: Yandex Cloud Foundation Models (OpenAI-совместимый API).
Спека: docs/services/llm.md  (этап M1)
"""

from __future__ import annotations

import json
from typing import Any, Literal

import httpx

from app.config import settings
from app.observability.logging import get_logger, track_llm_usage

logger = get_logger("kabi.llm")

Tier = Literal["primary", "cheap"]
EmbedKind = Literal["doc", "query"]

# 256-мерные эмбеддинги Yandex text-search-*
EMBED_DIM = 256

_embed_cache: dict[tuple[str, str], list[float]] = {}


class LLMError(RuntimeError):
    """Ошибка обращения к LLM-провайдеру."""


def _headers() -> dict[str, str]:
    if not settings.llm_api_key:
        raise LLMError("LLM_API_KEY не задан (.env)")
    headers = {
        "Authorization": f"Api-Key {settings.llm_api_key}",
        "Content-Type": "application/json",
    }
    if settings.llm_folder_id:
        headers["x-folder-id"] = settings.llm_folder_id
    return headers


def _model_for_tier(tier: Tier) -> str:
    model = settings.llm_model_primary if tier == "primary" else settings.llm_model_cheap
    if not model:
        raise LLMError(f"Модель для tier={tier} не сконфигурирована (.env)")
    return model


async def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{settings.llm_base_url.rstrip('/')}/{path.lstrip('/')}"
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, headers=_headers(), json=payload)
    if resp.status_code != 200:
        raise LLMError(f"{path} → HTTP {resp.status_code}: {resp.text[:500]}")
    return resp.json()


def _track(data: dict[str, Any]) -> None:
    usage = data.get("usage") or {}
    model = data.get("model", "unknown")
    track_llm_usage(
        model=model,
        prompt_tokens=int(usage.get("prompt_tokens", 0)),
        completion_tokens=int(usage.get("completion_tokens", 0)),
    )


async def complete(
    prompt: str,
    *,
    system: str | None = None,
    tier: Tier = "primary",
    temperature: float = 0.3,
    max_tokens: int = 2000,
) -> str:
    """Запрос к чат-модели выбранного уровня. Возвращает текст ответа."""
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    data = await _post(
        "chat/completions",
        {
            "model": _model_for_tier(tier),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
    )
    _track(data)
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise LLMError(f"Неожиданный ответ chat/completions: {data}") from exc


async def complete_json(
    prompt: str,
    *,
    system: str | None = None,
    tier: Tier = "primary",
) -> Any:
    """Как complete(), но парсит ответ как JSON (для структурного извлечения).

    Устойчиво к обёрткам ```json ... ``` вокруг ответа модели.
    """
    raw = await complete(prompt, system=system, tier=tier, temperature=0.0)
    return _parse_json_loose(raw)


def _parse_json_loose(raw: str) -> Any:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1] if "```" in text[3:] else text.strip("`")
        text = text.removeprefix("json").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


async def embed(text: str, *, kind: EmbedKind = "query") -> list[float]:
    """Вернуть 256-мерный эмбеддинг текста. Кэшируется по (модель, текст)."""
    model = (
        settings.llm_model_embed_doc if kind == "doc" else settings.llm_model_embed_query
    )
    if not model:
        raise LLMError(f"Модель эмбеддингов kind={kind} не сконфигурирована (.env)")

    cache_key = (model, text)
    if cache_key in _embed_cache:
        return _embed_cache[cache_key]

    data = await _post("embeddings", {"model": model, "input": text})
    try:
        vector = data["data"][0]["embedding"]
    except (KeyError, IndexError) as exc:
        raise LLMError(f"Неожиданный ответ embeddings: {data}") from exc

    _embed_cache[cache_key] = vector
    return vector
