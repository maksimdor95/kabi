"""Коннектор вакансий SuperJob (api.superjob.ru).

Порт логики из Leo AI (scraper.ts → scrapeSuperJobViaAPI / parseSuperJobVacancy).
Аутентификация через заголовок X-Api-App-Id (secret key v3....).

Маппинг полей по докам API v2.0:
    place_of_work.id: 2 = на дому (remote), 3 = разъездной, иначе office
Спека: docs/services/ingestion.md (этап M2)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings
from app.ingestion.schemas import OpportunityDraft
from app.observability.logging import get_logger

logger = get_logger("kabi.ingestion.superjob")


def _headers() -> dict[str, str]:
    return {
        "User-Agent": settings.hh_user_agent,
        "X-Api-App-Id": settings.superjob_api_key,
    }


def _parse_salary(item: dict[str, Any]) -> dict | None:
    lo = item.get("payment_from") or None
    hi = item.get("payment_to") or None
    if not lo and not hi:
        return None
    currency = (item.get("currency") or "rub").upper()
    return {"min": lo, "max": hi, "currency": currency}


def normalize_vacancy(item: dict[str, Any]) -> OpportunityDraft | None:
    title = item.get("profession")
    company = item.get("firm_name")
    if not title or not company:
        return None

    town = item.get("town") or {}
    location = town.get("title") if isinstance(town, dict) else None

    work = item.get("work") if isinstance(item.get("work"), str) else ""
    compensation = (
        item.get("compensation") if isinstance(item.get("compensation"), str) else ""
    )
    candidat = item.get("candidat") if isinstance(item.get("candidat"), str) else ""
    description = "\n\n".join(p for p in [work, compensation, candidat] if p).strip()

    place = item.get("place_of_work") or {}
    remote = isinstance(place, dict) and place.get("id") == 2

    link = item.get("link") or f"https://www.superjob.ru/vakansii/{item.get('id', '')}.html"

    posted_at = None
    date_pub = item.get("date_published")
    if isinstance(date_pub, (int, float)):
        posted_at = datetime.fromtimestamp(date_pub, tz=timezone.utc)

    return OpportunityDraft(
        type="job",
        title=title,
        org=company,
        description=description,
        location=location,
        remote=remote,
        salary=_parse_salary(item),
        url=link,
        source="superjob.ru",
        external_id=str(item.get("id")) if item.get("id") else None,
        posted_at=posted_at,
    )


class SuperJobConnector:
    source = "superjob.ru"

    def __init__(self, per_keyword: int | None = None) -> None:
        self.per_keyword = per_keyword or settings.ingestion_per_keyword

    async def fetch(
        self, keywords: list[str], *, area: int | None = None
    ) -> list[OpportunityDraft]:
        if not settings.superjob_api_key:
            logger.warning("SUPERJOB_API_KEY не задан — пропускаю SuperJob")
            return []

        count = min(self.per_keyword, 100)
        results: list[OpportunityDraft] = []
        async with httpx.AsyncClient(timeout=15) as client:
            for keyword in keywords[: settings.ingestion_keyword_limit]:
                try:
                    resp = await client.get(
                        f"{settings.superjob_api_url}/vacancies/",
                        params={
                            "keyword": keyword,
                            "page": 0,
                            "count": count,
                            "town": settings.superjob_town,
                        },
                        headers=_headers(),
                    )
                    if resp.status_code != 200:
                        logger.warning(
                            "SuperJob %s → HTTP %s: %s",
                            keyword,
                            resp.status_code,
                            resp.text[:200],
                        )
                        continue
                    objects = resp.json().get("objects", [])
                    logger.info("SuperJob '%s': %d вакансий", keyword, len(objects))
                    for item in objects:
                        draft = normalize_vacancy(item)
                        if draft:
                            results.append(draft)
                except httpx.HTTPError as exc:
                    logger.warning("SuperJob запрос '%s' упал: %s", keyword, exc)
                await asyncio.sleep(0.55)
        return results
