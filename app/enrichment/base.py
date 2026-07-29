"""Единый интерфейс источника обогащения. Спека: docs/services/enrichment.md

Правило: только собственные публичные источники пользователя, с его согласия.
Никакого автосбора данных о третьих лицах.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.enrichment.signals import ProfileSignals
from app.enrichment.sources.generic import GenericSource
from app.enrichment.sources.hh import HHSource
from app.enrichment.sources.linkedin import LinkedInSource
from app.enrichment.sources.talks import TalksSource
from app.observability.logging import get_logger

logger = get_logger("kabi.enrichment")

__all__ = [
    "ProfileSignals",
    "EnrichmentSource",
    "pick_source",
    "merge_signals",
    "signals_to_profile_patch",
    "format_signals_summary",
    "enrich_from_links",
]


class EnrichmentSource(Protocol):
    name: str

    def matches(self, url: str) -> bool:
        """Подходит ли этот источник для данной ссылки."""
        ...

    async def fetch(self, url: str) -> ProfileSignals:
        """Извлечь сигналы профиля из ссылки пользователя."""
        ...


# Порядок важен: специфичные источники раньше generic-fallback.
# Личный сайт / портфолио — через generic (без заточи под конкретный домен).
_SOURCES: list[EnrichmentSource] = [
    HHSource(),
    LinkedInSource(),
    TalksSource(),
    GenericSource(),
]


def pick_source(url: str) -> EnrichmentSource | None:
    for source in _SOURCES:
        if source.matches(url):
            return source
    return None


def merge_signals(*parts: ProfileSignals) -> ProfileSignals:
    topics: list[str] = []
    skills: list[str] = []
    links: list[str] = []
    notes: list[str] = []
    status: str | None = None
    for part in parts:
        for t in part.speaking_topics:
            if t and t not in topics:
                topics.append(t)
        for s in part.extra_skills:
            if s and s not in skills:
                skills.append(s)
        for link in part.source_links:
            if link and link not in links:
                links.append(link)
        notes.extend(part.notes)
        if part.job_search_status and status is None:
            status = part.job_search_status
    return ProfileSignals(
        speaking_topics=topics,
        extra_skills=skills,
        job_search_status=status,
        source_links=links,
        notes=notes,
    )


def signals_to_profile_patch(
    signals: ProfileSignals,
    *,
    existing_skills: list[str] | None = None,
    existing_topics: list[str] | None = None,
) -> dict:
    """Превратить сигналы в патч профиля (без затирания уже известных полей)."""
    skills = list(existing_skills or [])
    topics = list(existing_topics or [])
    patch: dict = {}
    for t in signals.speaking_topics:
        if t and t not in topics:
            topics.append(t)
    if topics != list(existing_topics or []):
        patch["speaking_topics"] = topics
    for s in signals.extra_skills:
        if s and s not in skills:
            skills.append(s)
    if skills != list(existing_skills or []):
        patch["skills"] = skills
    if signals.job_search_status:
        patch["job_search_status"] = signals.job_search_status
    if signals.source_links:
        patch["source_links"] = {"links": signals.source_links}
    return patch


def format_signals_summary(signals: ProfileSignals) -> str:
    """Короткое подтверждение; детали — в /profile, без повторного CTA."""
    has_data = bool(
        signals.speaking_topics or signals.extra_skills or signals.job_search_status
    )
    if not has_data and not signals.notes:
        return "По ссылкам пока ничего полезного не вытащил — продолжим вопросами."
    if not has_data and signals.notes:
        # Только служебные заметки (login-wall и т.п.) — без простыни «тем/навыков».
        return "\n".join(signals.notes[:3])
    return "Учёл ссылки в профиле (темы, навыки)."


async def enrich_from_links(user_id: UUID | None, links: list[str]) -> ProfileSignals:
    """Маршрутизировать ссылки по источникам и собрать сигналы."""
    del user_id  # на будущее (логирование / квоты); сейчас не нужен
    parts: list[ProfileSignals] = []
    for url in links:
        source = pick_source(url)
        if source is None:
            logger.info("enrich_skip unknown_url=%s", url)
            continue
        try:
            part = await source.fetch(url)
            parts.append(part)
            logger.info("enrich_ok source=%s url=%s", source.name, url)
        except Exception:  # noqa: BLE001
            logger.exception("enrich_failed source=%s url=%s", source.name, url)
            parts.append(
                ProfileSignals(source_links=[url], notes=[f"Не удалось прочитать {url}"])
            )
    return merge_signals(*parts) if parts else ProfileSignals()
