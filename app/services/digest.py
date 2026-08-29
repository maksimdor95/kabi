"""Сборка подборок: ingest → match → карточки.

Потоки:
  /today  — вакансии
  /pitch  — СМИ/подкасты для питча (без выдуманных дедлайнов)
  /talks  — конференции с известной датой CFP (deadlines.py)

Спека: docs/services/scheduler.md + matching.md (M2/M3).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select, update
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
    description: str | None = None
    # Pitch 2.0 — витрина СМИ/подкастов
    approach: str | None = None  # «Как зайти»
    how: str | None = None
    kind: str | None = None
    actionable: bool = True
    hide_url: bool = False  # homepage без tips — не светим как CTA


def _talk_link_label(opp: Opportunity) -> str | None:
    """Честная подпись ссылки. Homepage без tips/формы → None (скрываем CTA-ссылку)."""
    if (opp.type or "job") != "talk":
        return "Открыть вакансию →"
    meta = opp.meta if isinstance(opp.meta, dict) else {}
    cfp = meta.get("cfp_url")
    pitch = meta.get("pitch_url")
    if is_actionable_cfp_url(cfp):
        return "Открыть страницу заявки →"
    if is_actionable_cfp_url(pitch):
        return "Как подать / tips →"
    return None


def _fmt_item(match: Match, opp: Opportunity) -> DigestItem:
    meta = opp.meta if isinstance(opp.meta, dict) else {}
    how_to = meta.get("how_to") if isinstance(meta.get("how_to"), str) else None
    link_label = _talk_link_label(opp)
    hide_url = (opp.type or "job") == "talk" and link_label is None
    return DigestItem(
        match_id=str(match.id),
        score=match.score,
        reason=match.reason or "",
        title=opp.title,
        org=opp.org,
        location=opp.location,
        remote=opp.remote,
        salary=opp.salary,
        url=None if hide_url else opp.url,
        source=opp.source,
        opp_type=opp.type or "job",
        deadline=opp.deadline,
        link_label=link_label,
        description=opp.description,
        approach=(how_to.strip() if how_to and how_to.strip() else None),
        how=str(meta["how"]) if meta.get("how") else None,
        kind=str(meta["kind"]) if meta.get("kind") else None,
        actionable=bool(meta.get("actionable", True)),
        hide_url=hide_url,
    )


async def list_pending(
    session: AsyncSession,
    profile: Profile,
    *,
    scope: MatchScope = "jobs",
    limit: int = 7,
) -> list[DigestItem]:
    """Неотреагированные карточки (Match.status=new) для витрины Mini App.

    `build_digest` создаёт только *новые* Match и поэтому возвращает [] если
    бот/расписание уже сматчили всех кандидатов. Здесь читаем то, что ещё
    ждёт реакции — иначе приложение выглядит пустым при полных карманах.
    """
    stmt = (
        select(Match, Opportunity)
        .join(Opportunity, Opportunity.id == Match.opportunity_id)
        .where(Match.profile_id == profile.id, Match.status == "new")
        .order_by(Match.score.desc().nulls_last(), Match.created_at.desc())
    )
    if scope == "jobs":
        stmt = stmt.where(Opportunity.type == "job").limit(limit)
    else:
        # pitch фильтруем evergreen в Python — в SQL нет is_evergreen_pitch.
        stmt = stmt.where(Opportunity.type == "talk").limit(max(limit * 4, 20))

    rows = (await session.execute(stmt)).all()
    items: list[DigestItem] = []
    for match, opp in rows:
        if scope == "pitch" and not matching.is_evergreen_pitch(opp):
            continue
        if scope == "talks" and matching.is_evergreen_pitch(opp):
            # talks = CFP/сроки; evergreen уезжает в /pitch
            continue
        items.append(_fmt_item(match, opp))
        if len(items) >= limit:
            break
    return items


async def mark_shown(session: AsyncSession, match_ids: list[str]) -> int:
    """Пометить карточки доставленными (Pitch 2.0 / anti-spam)."""
    if not match_ids:
        return 0
    ids: list = []
    for raw in match_ids:
        try:
            import uuid as _uuid

            ids.append(_uuid.UUID(str(raw)))
        except ValueError:
            continue
    if not ids:
        return 0
    now = datetime.now(timezone.utc)
    result = await session.execute(
        update(Match)
        .where(Match.id.in_(ids), Match.shown_at.is_(None))
        .values(shown_at=now)
    )
    rowcount = getattr(result, "rowcount", None)
    return int(rowcount or 0)


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
