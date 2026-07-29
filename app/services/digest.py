"""Сборка подборок: ingest → match → карточки.

Потоки:
  /today  — вакансии
  /pitch  — СМИ/подкасты для питча (без выдуманных дедлайнов)
  /talks  — конференции с известной датой CFP (deadlines.py)

Спека: docs/services/scheduler.md + matching.md (M2/M3).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Match, Opportunity, Profile
from app.ingestion.runner import ingest_for_profile
from app.ingestion.talks.url_quality import is_actionable_cfp_url
from app.observability.logging import get_logger
from app.services import matching
from app.services import profile as profile_service
from app.services import schedule as schedule_service
from app.services.matching import MatchScope, RankMode

logger = get_logger("kabi.digest")


@dataclass
class DigestItem:
    match_id: str
    score: float
    reason: str
    title: str
    org: str | None
    location: str | None
    remote: bool
    salary: dict | None
    url: str | None
    source: str | None
    opp_type: str = "job"  # job | talk
    deadline: datetime | None = None
    link_label: str | None = None


def _talk_link_label(opp: Opportunity) -> str:
    """Честная подпись ссылки: не выдаём главную страницу за форму заявки."""
    if (opp.type or "job") != "talk":
        return "Открыть вакансию →"
    meta = opp.meta or {}
    cfp = meta.get("cfp_url") if isinstance(meta, dict) else None
    if is_actionable_cfp_url(cfp):
        return "Открыть страницу заявки →"
    return "Открыть сайт →"


def _fmt_item(match: Match, opp: Opportunity) -> DigestItem:
    return DigestItem(
        match_id=str(match.id),
        score=match.score,
        reason=match.reason or "",
        title=opp.title,
        org=opp.org,
        location=opp.location,
        remote=opp.remote,
        salary=opp.salary,
        url=opp.url,
        source=opp.source,
        opp_type=opp.type or "job",
        deadline=opp.deadline,
        link_label=_talk_link_label(opp),
    )


async def build_digest(
    session: AsyncSession,
    profile: Profile,
    *,
    scope: MatchScope = "jobs",
    do_ingest: bool = True,
    include_talks: bool = False,
    live_cfp: bool = False,
    limit: int = 7,
    rank_mode: RankMode | None = None,
    max_age_hours: float | None = None,
) -> list[DigestItem]:
    """Собрать подборку: jobs / pitch / talks."""
    if profile.embedding is None:
        await profile_service.compute_embedding(session, profile)

    if do_ingest:
        talks = include_talks or scope in ("pitch", "talks")
        await ingest_for_profile(
            session,
            profile,
            include_jobs=scope == "jobs",
            include_talks=talks,
            live_cfp=live_cfp,
        )

    sched = schedule_service.normalize_schedule(profile.digest_schedule)
    mode: RankMode = rank_mode or sched.get("rank_mode") or "fresh_relevant"  # type: ignore[assignment]
    if mode not in ("fresh_relevant", "relevant"):
        mode = "fresh_relevant"

    new_matches = await matching.match(
        session,
        profile,
        limit=limit,
        scope=scope,
        rank_mode=mode,
        max_age_hours=max_age_hours,
    )
    if not new_matches:
        return []

    opp_ids = [m.opportunity_id for m in new_matches]
    opps = {
        o.id: o
        for o in (
            await session.execute(select(Opportunity).where(Opportunity.id.in_(opp_ids)))
        ).scalars()
    }
    return [_fmt_item(m, opps[m.opportunity_id]) for m in new_matches if m.opportunity_id in opps]
