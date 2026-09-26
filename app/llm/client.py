"""Клиент LLM с роутингом моделей (primary/cheap) и эмбеддингами.

Провайдер: Yandex Cloud Foundation Models (OpenAI-совместимый API).
Спека: docs/services/llm.md  (этап M1)
"""

from __future__ import annotations

import asyncio
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

# Free-tier Yandex: ~10 concurrent sessions / ~10 embed RPS.
# Держим ниже квоты, иначе 429 на refresh Mini App / ingest.
_CHAT_CONCURRENCY = 3
_EMBED_CONCURRENCY = 2
_POST_MAX_ATTEMPTS = 5
_POST_RETRY_BASE_SEC = 0.6

_embed_cache: dict[tuple[str, str], list[float]] = {}
_chat_sem = asyncio.Semaphore(_CHAT_CONCURRENCY)
_embed_sem = asyncio.Semaphore(_EMBED_CONCURRENCY)


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


def _is_rate_limited(status_code: int, body: str) -> bool:
    if status_code == 429:
        return True
    low = body.lower()
    return status_code == 400 and (
        "rate_limit" in low or "quota" in low or "limit exceed" in low
    )


async def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST с ретраем на 429/quota и семафором по типу endpoint."""
    url = f"{settings.llm_base_url.rstrip('/')}/{path.lstrip('/')}"
    sem = _embed_sem if path.lstrip("/").startswith("embeddings") else _chat_sem
    last_err: LLMError | None = None

    async with sem:
        for attempt in range(1, _POST_MAX_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(timeout=60) as client:
                    resp = await client.post(url, headers=_headers(), json=payload)
            except httpx.HTTPError as exc:
                last_err = LLMError(f"{path} → network: {exc}")
                if attempt >= _POST_MAX_ATTEMPTS:
                    raise last_err from exc
                await asyncio.sleep(_POST_RETRY_BASE_SEC * (2 ** (attempt - 1)))
                continue

            if resp.status_code == 200:
                return resp.json()

            body = resp.text[:500]
            if _is_rate_limited(resp.status_code, body) and attempt < _POST_MAX_ATTEMPTS:
                delay = _POST_RETRY_BASE_SEC * (2 ** (attempt - 1))
                logger.warning(
                    "llm_rate_limited path=%s attempt=%s/%s sleep=%.1fs",
                    path,
                    attempt,
                    _POST_MAX_ATTEMPTS,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            raise LLMError(f"{path} → HTTP {resp.status_code}: {body}")

    raise last_err or LLMError(f"{path} → failed after retries")


def _track(data: dict[str, Any]) -> None:
    usage = data.get("usage") or {}
    model = data.get("model", "unknown")
    track_llm_usage(
        model=model,
        prompt_tokens=int(usage.get("prompt_tokens", 0)),
        completion_tokens=int(usage.get("completion_tokens", 0)),
    )


async def complete_messages(
    messages: list[dict[str, str]],
    *,
    tier: Tier = "primary",
    temperature: float = 0.3,
    max_tokens: int = 2000,
) -> str:
    """Запрос к чат-модели с готовым списком messages (system/user/assistant)."""
    if not messages:
        raise LLMError("complete_messages: пустой messages")
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
    return await complete_messages(
        messages, tier=tier, temperature=temperature, max_tokens=max_tokens
    )


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
