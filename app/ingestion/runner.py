"""Runner ингестии: jobs + talks → dedup → save → embed(doc).

Спека: docs/services/ingestion.md (этапы M2/M3)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Opportunity, Profile
from app.ingestion.base import JobConnector
from app.ingestion.jobs.career_sites_connector import CareerSitesConnector
from app.ingestion.jobs.getmatch_connector import GetmatchConnector
from app.ingestion.jobs.habr_connector import HabrCareerConnector
from app.ingestion.jobs.hh_connector import HHConnector
from app.ingestion.jobs.superjob_connector import SuperJobConnector
from app.ingestion.jobs.tg_connector import TelegramJobsConnector
from app.ingestion.keywords import derive_hh_area, derive_keywords
from app.ingestion.schemas import OpportunityDraft
from app.ingestion.talks.discover_connector import CfpDiscoveryConnector
from app.ingestion.talks.open_cfp_connector import OpenCfpConnector
from app.ingestion.talks.seed_connector import TalkPlacesConnector
from app.llm import client as llm
from app.observability.logging import get_logger

logger = get_logger("kabi.ingestion.runner")

_EMBED_CONCURRENCY = 8


@dataclass
class IngestionResult:
    fetched: int
    saved: int
    skipped_existing: int


def default_job_connectors() -> list[JobConnector]:
    """HH/SJ + M7: TG, career sites, Getmatch, Habr Career."""
    return [
        HHConnector(),
        SuperJobConnector(),
        TelegramJobsConnector(),
        CareerSitesConnector(),
        GetmatchConnector(),
        HabrCareerConnector(),
    ]


def _dedup_drafts(drafts: list[OpportunityDraft]) -> list[OpportunityDraft]:
    seen: set[tuple[str | None, str | None]] = set()
    unique: list[OpportunityDraft] = []
    for d in drafts:
        key = (d.source, d.external_id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(d)
    return unique


async def _load_existing_map(
    session: AsyncSession, drafts: list[OpportunityDraft]
) -> dict[tuple[str, str], Opportunity]:
    keys = {(d.source, d.external_id) for d in drafts if d.source and d.external_id}
    if not keys:
        return {}
    sources = {s for s, _ in keys}
    rows = (
        await session.execute(
            select(Opportunity).where(
                Opportunity.source.in_(sources),
                Opportunity.external_id.is_not(None),
            )
        )
    ).scalars().all()
    return {(o.source, o.external_id): o for o in rows if o.source and o.external_id}


async def _embed_many(texts: list[str]) -> list[list[float] | None]:
    """Параллельные эмбеддинги с лимитом concurrency."""
    if not texts:
        return []
    sem = asyncio.Semaphore(_EMBED_CONCURRENCY)

    async def one(text: str) -> list[float] | None:
        async with sem:
            try:
                return await llm.embed(text, kind="doc")
            except Exception as exc:
                logger.warning("embed failed: %s", exc)
                return None

    return list(await asyncio.gather(*(one(t) for t in texts)))


async def _save_drafts(
    session: AsyncSession,
    drafts: list[OpportunityDraft],
    *,
    upsert: bool = False,
) -> IngestionResult:
    drafts = _dedup_drafts(drafts)
    existing_map = await _load_existing_map(session, drafts)
    existing_keys = set(existing_map)
    saved = 0
    skipped = 0
    updated = 0

    # Сначала собираем объекты и тексты для эмбеддинга — считаем пачкой.
    pending: list[tuple[Opportunity, str]] = []

    for draft in drafts:
        key = (draft.source, draft.external_id)
        desc = draft.description or ""
        if draft.tags:
            desc = (desc + "\nТемы: " + ", ".join(draft.tags)).strip()

        if key in existing_map and upsert:
            opp = existing_map[key]
            changed = False
            # Явно обновляем и сброс deadline=None (убрать фейковые soft-даты СМИ).
            if draft.deadline != opp.deadline:
                opp.deadline = draft.deadline
                changed = True
            if desc and desc != (opp.description or ""):
                opp.description = desc
                changed = True
            if draft.title and draft.title != opp.title:
                opp.title = draft.title
                changed = True
            if draft.url and draft.url != opp.url:
                opp.url = draft.url
                changed = True
            if draft.meta and draft.meta != (opp.meta or {}):
                opp.meta = draft.meta
                changed = True
            if changed:
                text = draft.to_text()
                if text:
                    pending.append((opp, text))
                updated += 1
            else:
                skipped += 1
            continue

        if key in existing_keys:
            skipped += 1
            continue

        opp = Opportunity(
            type=draft.type,
            title=draft.title,
            org=draft.org,
            description=desc,
            location=draft.location,
            remote=draft.remote,
            salary=draft.salary,
            deadline=draft.deadline,
            url=draft.url,
            source=draft.source,
            external_id=draft.external_id,
            meta=draft.meta or None,
        )
        session.add(opp)
        text = draft.to_text()
        if text:
            pending.append((opp, text))
        saved += 1

    if pending:
        vectors = await _embed_many([t for _, t in pending])
        for (opp, _), vec in zip(pending, vectors, strict=True):
            if vec is not None:
                opp.embedding = vec

    await session.flush()
    if updated:
        logger.info("upsert: updated=%d", updated)
    return IngestionResult(
        fetched=len(drafts),
        saved=saved + updated,
        skipped_existing=skipped,
    )


async def ingest_jobs_for_profile(
    session: AsyncSession,
    profile: Profile,
    *,
    connectors: list[JobConnector] | None = None,
) -> IngestionResult:
    connectors = connectors or default_job_connectors()
    keywords = derive_keywords(profile)
    area = derive_hh_area(profile)
    if not keywords:
        logger.warning("У профиля нет ролей — нечего искать")
        return IngestionResult(fetched=0, saved=0, skipped_existing=0)

    logger.info("Ингестия jobs: keywords=%s area=%s", keywords, area)
    drafts: list[OpportunityDraft] = []
    for connector in connectors:
        try:
            drafts.extend(await connector.fetch(keywords, area=area))
        except Exception as exc:
            logger.warning("Коннектор %s упал: %s", connector.source, exc)

    result = await _save_drafts(session, drafts)
    logger.info(
        "Ингестия jobs: fetched=%d saved=%d skipped=%d",
        result.fetched,
        result.saved,
        result.skipped_existing,
    )
    return result


async def ingest_talks(
    session: AsyncSession,
    *,
    live_cfp: bool = True,
    discover_cfp: bool | None = None,
    profile: Profile | None = None,
) -> IngestionResult:
    """Seed-медиа + bootstrap open_cfp + M6 discovery (PaperCall и др.).

    discover_cfp по умолчанию = live_cfp (ночной прогон включает discovery).
    """
    do_discover = live_cfp if discover_cfp is None else discover_cfp
    drafts: list[OpportunityDraft] = []
    drafts.extend(await TalkPlacesConnector(live_cfp=False).fetch())
    if live_cfp:
        try:
            drafts.extend(await OpenCfpConnector().fetch())
        except Exception as exc:
            logger.warning("OpenCfpConnector упал: %s", exc)
    if do_discover:
        try:
            niche_kw = None
            roles = None
            if profile is not None:
                from app.ingestion.talks.discovery_filters import profile_niche_keywords

                niche_kw = profile_niche_keywords(
                    speaking_topics=list(profile.speaking_topics or []),
                    roles=list(profile.roles or []),
                    skills=list(profile.skills or []),
                )
                roles = derive_keywords(profile)
            drafts.extend(
                await CfpDiscoveryConnector(niche_keywords=niche_kw).fetch(roles)
            )
        except Exception as exc:
            logger.warning("CfpDiscoveryConnector упал: %s", exc)
    result = await _save_drafts(session, drafts, upsert=True)
    logger.info(
        "Ингестия talks: fetched=%d saved=%d skipped=%d (live_cfp=%s discover=%s)",
        result.fetched,
        result.saved,
        result.skipped_existing,
        live_cfp,
        do_discover,
    )
    return result


async def ingest_for_profile(
    session: AsyncSession,
    profile: Profile,
    *,
    include_jobs: bool = True,
    include_talks: bool = True,
    live_cfp: bool = True,
) -> IngestionResult:
    """Полная ингестия под приоритеты профиля.

    live_cfp=False — только seed без HTTP+LLM по страницам CFP (для /today).
    """
    prio = profile.priorities or "both"
    want_jobs = include_jobs and prio in ("job", "both")
    want_talks = include_talks and prio in ("talk", "both")

    total = IngestionResult(fetched=0, saved=0, skipped_existing=0)
    if want_jobs:
        r = await ingest_jobs_for_profile(session, profile)
        total = IngestionResult(
            fetched=total.fetched + r.fetched,
            saved=total.saved + r.saved,
            skipped_existing=total.skipped_existing + r.skipped_existing,
        )
    if want_talks:
        r = await ingest_talks(session, live_cfp=live_cfp, profile=profile)
        total = IngestionResult(
            fetched=total.fetched + r.fetched,
            saved=total.saved + r.saved,
            skipped_existing=total.skipped_existing + r.skipped_existing,
        )
    return total
