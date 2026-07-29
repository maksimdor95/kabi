"""Коннектор вакансий HeadHunter (api.hh.ru).

Порт логики из Leo AI (services/job-matching/src/services/scraper.ts →
scrapeHHViaAPI). Используем публичный поиск /vacancies с APPL-токеном
приложения. Детали берём прямо из элементов выдачи (snippet), без
дополнительного запроса /vacancies/{id} — так быстрее и достаточно для мэтчинга.

Спека: docs/services/ingestion.md (этап M2)
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import httpx

from app.config import settings
from app.ingestion.schemas import OpportunityDraft
from app.observability.logging import get_logger

logger = get_logger("kabi.ingestion.hh")

_CURRENCY_MAP = {"RUR": "RUB"}


def _headers() -> dict[str, str]:
    headers = {
        "User-Agent": settings.hh_user_agent,
        "HH-User-Agent": settings.hh_user_agent,
    }
    if settings.hh_api_key:
        headers["Authorization"] = f"Bearer {settings.hh_api_key}"
    return headers


def _parse_salary(raw: dict[str, Any] | None) -> dict | None:
    if not raw:
        return None
    lo = raw.get("from")
    hi = raw.get("to")
    if not lo and not hi:
        return None
    currency = raw.get("currency") or "RUB"
    return {
        "min": lo,
        "max": hi,
        "currency": _CURRENCY_MAP.get(currency, currency),
    }


def _is_remote(item: dict[str, Any]) -> bool:
    schedule = (item.get("schedule") or {}).get("id")
    if schedule == "remote":
        return True
    for wf in item.get("work_format") or []:
        if (wf.get("id") or "").upper() == "REMOTE":
            return True
    return False


def _description(item: dict[str, Any]) -> str:
    snippet = item.get("snippet") or {}
    parts = [snippet.get("responsibility"), snippet.get("requirement")]
    return "\n".join(p for p in parts if p).strip()


def _parse_posted_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def normalize_vacancy(item: dict[str, Any]) -> OpportunityDraft | None:
    title = item.get("name")
    if not title:
        return None
    employer = (item.get("employer") or {}).get("name")
    area = (item.get("area") or {}).get("name")
    return OpportunityDraft(
        type="job",
        title=title,
        org=employer,
        description=_description(item),
        location=area,
        remote=_is_remote(item),
        salary=_parse_salary(item.get("salary")),
        url=item.get("alternate_url"),
        source="hh.ru",
        external_id=str(item.get("id")) if item.get("id") else None,
        posted_at=_parse_posted_at(item.get("published_at")),
    )


class HHConnector:
    source = "hh.ru"

    def __init__(self, per_keyword: int | None = None) -> None:
        self.per_keyword = per_keyword or settings.ingestion_per_keyword

    async def fetch(
        self, keywords: list[str], *, area: int | None = None
    ) -> list[OpportunityDraft]:
        if not settings.hh_api_key:
            logger.warning("HH_API_KEY не задан — пропускаю HH")
            return []

        per_page = min(self.per_keyword, 100)
        results: list[OpportunityDraft] = []
        async with httpx.AsyncClient(timeout=15) as client:
            for keyword in keywords[: settings.ingestion_keyword_limit]:
                try:
                    params: dict[str, Any] = {"text": keyword, "per_page": per_page, "page": 0}
                    if area is not None:
                        params["area"] = area
                    resp = await client.get(
                        f"{settings.hh_api_url}/vacancies",
                        params=params,
                        headers=_headers(),
                    )
                    if resp.status_code != 200:
                        logger.warning(
                            "HH %s → HTTP %s: %s", keyword, resp.status_code, resp.text[:200]
                        )
                        continue
                    items = resp.json().get("items", [])
                    logger.info("HH '%s': %d вакансий", keyword, len(items))
                    for item in items:
                        draft = normalize_vacancy(item)
                        if draft:
                            results.append(draft)
                except httpx.HTTPError as exc:
                    logger.warning("HH запрос '%s' упал: %s", keyword, exc)
                await asyncio.sleep(0.2)
        return results
