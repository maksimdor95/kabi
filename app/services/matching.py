"""Мэтчинг профиля с возможностями: хард-фильтры + pgvector + объяснение.

Потоки (не мешать):
  • /today  — вакансии
  • /pitch  — evergreen-питч (СМИ/подкасты без дедлайна)
  • /talks  — конференции с известной датой CFP (см. deadlines.py)
Спека: docs/services/matching.md
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Match, Opportunity, Profile
from app.llm import client as llm
from app.observability.logging import get_logger
from app.services.profile import profile_to_text

logger = get_logger("kabi.matching")

_POOL_SIZE = 50
_DEFAULT_LIMIT = 7
_TOKEN_RE = re.compile(r"[a-zа-яё0-9]{2,}", re.I)
# Статусы seed/live, которые не стоит предлагать как «сейчас можно».
_INACTIVE_TALK_STATUS = frozenset({"closed", "watch"})
# Конференции/CFP — только в /talks.
_CFP_KINDS = frozenset({"conference"})
_CFP_HOWS = frozenset({"cfp_talk"})

MatchScope = Literal["jobs", "pitch", "talks"]
RankMode = Literal["fresh_relevant", "relevant"]

_FRESH_ALPHA = 0.65  # вес similarity в fresh_relevant
_FRESH_HALF_LIFE_H = 72.0


@dataclass
class Candidate:
    opportunity: Opportunity
    score: float


def _recency_score(fetched_at: datetime | None, *, now: datetime) -> float:
    if fetched_at is None:
        return 0.0
    ft = fetched_at
    if ft.tzinfo is None:
        ft = ft.replace(tzinfo=timezone.utc)
    age_h = max(0.0, (now - ft.astimezone(timezone.utc)).total_seconds() / 3600.0)
    return 0.5 ** (age_h / _FRESH_HALF_LIFE_H)


def _blend_score(similarity: float, fetched_at: datetime | None, *, now: datetime) -> float:
    rec = _recency_score(fetched_at, now=now)
    return round(_FRESH_ALPHA * similarity + (1.0 - _FRESH_ALPHA) * rec, 4)


def _hard_no_terms(profile: Profile) -> list[str]:
    terms: list[str] = []
    for value in (profile.hard_nos or {}).values():
        if isinstance(value, str):
            terms.append(value)
        elif isinstance(value, (list, tuple)):
            terms.extend(str(v) for v in value)
    return [t.strip().lower() for t in terms if t and str(t).strip()]


def _min_salary(profile: Profile) -> int | None:
    sal = profile.salary_expectation or {}
    value = sal.get("min") if isinstance(sal, dict) else None
    return int(value) if value else None


def is_evergreen_pitch(opp: Opportunity) -> bool:
    """СМИ/подкасты для питча: talk без дедлайна и не CFP-конференция."""
    if (getattr(opp, "type", None) or "job") != "talk":
        return False
    if getattr(opp, "deadline", None) is not None:
        return False
    meta = getattr(opp, "meta", None) or {}
    if not isinstance(meta, dict):
        return True
    kind = str(meta.get("kind") or "").lower()
    how = str(meta.get("how") or "").lower()
    if kind in _CFP_KINDS or how in _CFP_HOWS:
        return False
    return True


def _tokens(texts: list[str]) -> set[str]:
    out: set[str] = set()
    for text in texts:
        for m in _TOKEN_RE.findall(text or ""):
            out.add(m.lower())
    return out


def _profile_topic_tokens(profile: Profile) -> set[str]:
    """Темы/роли/скиллы профиля для пересечения с talk.topics."""
    parts: list[str] = []
    parts.extend(getattr(profile, "speaking_topics", None) or [])
    parts.extend(getattr(profile, "roles", None) or [])
    parts.extend(getattr(profile, "skills", None) or [])
    return _tokens(parts)


def _opp_topic_tokens(opp: Opportunity) -> set[str]:
    meta = getattr(opp, "meta", None) or {}
    topics = meta.get("topics") if isinstance(meta, dict) else None
    if isinstance(topics, list) and topics:
        return _tokens([str(t) for t in topics])
    # Fallback: «Темы: a, b» в description (старые записи без meta.topics).
    desc = opp.description or ""
    for line in desc.splitlines():
        low = line.lower()
        if low.startswith("темы") or "темы, которые" in low:
            _, _, rest = line.partition(":")
            if not rest:
                _, _, rest = line.partition("заходят:")
            return _tokens([rest])
    return set()


def _topics_overlap(profile_tokens: set[str], opp_tokens: set[str]) -> bool:
    """Пересечение тем: точное или мягкое (продукт ⊂ продуктом)."""
    if not profile_tokens or not opp_tokens:
        return True  # нет сигнала — не режем (эмбеддинг разберётся)
    if profile_tokens & opp_tokens:
        return True
    for a in profile_tokens:
        if len(a) < 4:
            continue
        for b in opp_tokens:
            if len(b) < 4:
                continue
            if a in b or b in a:
                return True
    return False


def _talk_status(opp: Opportunity) -> str:
    meta = getattr(opp, "meta", None) or {}
    if isinstance(meta, dict) and meta.get("status"):
        return str(meta["status"]).lower()
    return "open"


# Роли, которые не предлагаем CPO/HoP-профилю (технарь / PM проектов / масса).
_TECH_TITLE_RE = re.compile(
    r"(?:"
    r"\b(?:backend|frontend|fullstack|full[\s-]?stack|devops|sre|qa)\b|"
    r"\b(?:android|ios|flutter|golang|kotlin|php|java|python|c\+\+|embedded)\b|"
    r"(?:разработчик|программист|тестировщик|инженер\s+данных|data\s+engineer|"
    r"ml\s+engineer|системный\s+администратор)|"
    r"(?:курьер|водитель|оператор\s+колл)"
    r")",
    re.I,
)
_PROJECT_NOT_PRODUCT_RE = re.compile(
    r"(?:"
    r"\bproject\s+manager\b|"
    r"менеджер\s+проектов|"
    r"руководитель\s+проектов|"
    r"лидер\s+проекта|"
    r"ceo\s+проекта|"
    r"scrum\s+master|"
    r"бизнес[\s-]?аналитик|"
    r"business\s+analyst"
    r")",
    re.I,
)
# IC-роли рядом с «продуктом» (Product Designer / аналитик) — не CPO-трек.
_PRODUCT_IC_RE = re.compile(
    r"(?:"
    r"дизайнер|designer|"
    r"аналитик|analyst|"
    r"researcher|исследователь|"
    r"маркетолог|marketing\s+(?:manager|specialist)|"
    r"контент[\s-]?менеджер|copywriter|копирайтер|"
    r"рекрутер|recruiter|hr[\s-]?менеджер"
    r")",
    re.I,
)
_PRODUCT_LEADERSHIP_RE = re.compile(
    r"(?:"
    r"\bcpo\b|chief\s+product|"
    r"head\s+of\s+product|vp\s+product|vice\s+president\s+of\s+product|"
    r"директор\s+по\s+продукт|руководитель\s+(?:направления\s+)?продукт|"
    r"product\s+(?:lead|manager|owner|director|head)|"
    r"продакт[\s-]?менеджер|владелец\s+продукт|менеджер\s+продукт|"
    r"руководитель\s+направления|директор\s+по"
    r")",
    re.I,
)
_PRODUCT_SIGNAL_RE = re.compile(
    r"(?:"
    r"\bproduct\b|продукт|продакт|\bcpo\b|"
    r"product\s+owner|product\s+manager|product\s+lead|"
    r"head\s+of\s+product|директор\s+по\s+продукту|"
    r"руководитель\s+продукт|владелец\s+продукт"
    r")",
    re.I,
)


def _job_fits_product_track(opp: Opportunity, profile: Profile) -> bool:
    """Отсечь явный техтрек и «менеджер проектов» без product-сигнала."""
    title = opp.title or ""
    desc = (opp.description or "")[:600]
    blob = f"{title}\n{desc}"

    if _TECH_TITLE_RE.search(title) and not _PRODUCT_SIGNAL_RE.search(title):
        return False
    if _PROJECT_NOT_PRODUCT_RE.search(title) and not _PRODUCT_SIGNAL_RE.search(blob):
        return False

    roles_blob = " ".join(getattr(profile, "roles", None) or []).lower()
    product_profile = any(
        x in roles_blob
        for x in ("product", "продукт", "cpo", "продакт", "owner")
    )
    if product_profile:
        # «Product Designer» / «продуктовый аналитик» — не лидерский трек.
        if _PRODUCT_IC_RE.search(title) and not _PRODUCT_LEADERSHIP_RE.search(title):
            return False
        if not _PRODUCT_SIGNAL_RE.search(blob):
            return False
    return True


def passes_hard_filters(opp: Opportunity, profile: Profile) -> bool:
    """Хард-фильтры до ранжирования."""
    opp_type = getattr(opp, "type", None) or "job"

    if opp_type == "job":
        if profile.work_mode == "remote" and not opp.remote:
            return False
        min_salary = _min_salary(profile)
        if min_salary and opp.salary:
            ceiling = opp.salary.get("max") or opp.salary.get("min")
            if ceiling is not None and ceiling < min_salary:
                return False
        if not _job_fits_product_track(opp, profile):
            return False

    if opp_type == "talk":
        # closed/watch — не actionable прямо сейчас.
        if _talk_status(opp) in _INACTIVE_TALK_STATUS:
            return False
        if getattr(opp, "deadline", None) is not None:
            now = datetime.now(timezone.utc)
            dl = opp.deadline
            if dl.tzinfo is None:
                dl = dl.replace(tzinfo=timezone.utc)
            if dl < now:
                return False
        # Пересечение тем: иначе Forbes/YouTube матчатся на любой PO-профиль.
        if not _topics_overlap(_profile_topic_tokens(profile), _opp_topic_tokens(opp)):
            return False

    haystack = " ".join(
        p.lower() for p in [opp.title, opp.org or "", opp.description or ""] if p
    )
    for term in _hard_no_terms(profile):
        if term in haystack:
            return False

    return True


async def _already_matched_ids(session: AsyncSession, profile_id) -> set:
    rows = (
        await session.execute(
            select(Match.opportunity_id).where(Match.profile_id == profile_id)
        )
    ).scalars()
    return set(rows)


async def _rank_type(
    session: AsyncSession,
    profile: Profile,
    opp_type: str,
    *,
    limit: int,
    seen_matched: set,
    evergreen_only: bool = False,
    rank_mode: RankMode = "fresh_relevant",
    max_age_hours: float | None = None,
) -> list[Candidate]:
    dist = Opportunity.embedding.cosine_distance(profile.embedding).label("dist")
    stmt = (
        select(Opportunity, dist)
        .where(Opportunity.type == opp_type, Opportunity.embedding.is_not(None))
        .order_by(dist)
        .limit(_POOL_SIZE)
    )
    rows = (await session.execute(stmt)).all()
    now = datetime.now(timezone.utc)
    scored: list[Candidate] = []
    for opp, distance in rows:
        if opp.id in seen_matched:
            continue
        if not passes_hard_filters(opp, profile):
            continue
        if evergreen_only and not is_evergreen_pitch(opp):
            continue
        if max_age_hours is not None:
            ft = opp.fetched_at
            if ft is None:
                continue
            if ft.tzinfo is None:
                ft = ft.replace(tzinfo=timezone.utc)
            age_h = (now - ft.astimezone(timezone.utc)).total_seconds() / 3600.0
            if age_h > max_age_hours:
                continue
        sim = 1.0 - float(distance)
        if rank_mode == "relevant":
            score = round(sim, 4)
        else:
            score = _blend_score(sim, opp.fetched_at, now=now)
        scored.append(Candidate(opportunity=opp, score=score))

    if rank_mode == "fresh_relevant":
        scored.sort(key=lambda c: c.score, reverse=True)
    return scored[:limit]


async def rank_candidates(
    session: AsyncSession,
    profile: Profile,
    *,
    limit: int = _DEFAULT_LIMIT,
    scope: MatchScope = "jobs",
    rank_mode: RankMode = "fresh_relevant",
    max_age_hours: float | None = None,
) -> list[Candidate]:
    """Отобрать кандидатов по потоку: jobs / pitch (СМИ) / talks (все выступления)."""
    if profile.embedding is None:
        logger.warning("У профиля нет эмбеддинга — мэтчинг невозможен")
        return []

    seen_matched = await _already_matched_ids(session, profile.id)
    kw = dict(
        limit=limit,
        seen_matched=seen_matched,
        rank_mode=rank_mode,
        max_age_hours=max_age_hours,
    )
    if scope == "pitch":
        return await _rank_type(
            session, profile, "talk", evergreen_only=True, **kw  # type: ignore[arg-type]
        )
    if scope == "talks":
        return await _rank_type(
            session, profile, "talk", evergreen_only=False, **kw  # type: ignore[arg-type]
        )
    return await _rank_type(session, profile, "job", **kw)  # type: ignore[arg-type]


_EXPLAIN_SYSTEM = (
    "Ты — персональный карьерный менеджер. Кратко (1–2 предложения, по-русски) "
    "объясни, почему эта возможность подходит человеку. Опирайся ТОЛЬКО на факты из "
    "профиля и карточки, ничего не выдумывай. Без воды и без приветствий. "
    "Если это медиа/конференция — скажи, зачем туда идти (темы, формат)."
)


async def explain(profile: Profile, opp: Opportunity) -> str:
    kind = "ВАКАНСИЯ" if opp.type == "job" else "ПЛОЩАДКА / ВЫСТУПЛЕНИЕ"
    prompt = (
        f"ПРОФИЛЬ:\n{profile_to_text(profile)}\n\n"
        f"{kind}:\nНазвание: {opp.title}\n"
        f"Организация: {opp.org or '—'}\n"
        f"Локация: {opp.location or '—'}{' · удалённо' if opp.remote else ''}\n"
        f"Описание: {(opp.description or '')[:800]}\n\n"
        "Почему это подходит?"
    )
    try:
        return (await llm.complete(prompt, system=_EXPLAIN_SYSTEM, tier="cheap")).strip()
    except Exception as exc:
        logger.warning("Объяснение не сгенерировано: %s", exc)
        if opp.type == "talk":
            return "Площадка пересекается с твоими темами экспертности."
        return "Совпадение по роли и ключевым навыкам."


async def match(
    session: AsyncSession,
    profile: Profile,
    *,
    limit: int = _DEFAULT_LIMIT,
    scope: MatchScope = "jobs",
    rank_mode: RankMode = "fresh_relevant",
    max_age_hours: float | None = None,
) -> list[Match]:
    candidates = await rank_candidates(
        session,
        profile,
        limit=limit,
        scope=scope,
        rank_mode=rank_mode,
        max_age_hours=max_age_hours,
    )
    if not candidates:
        return []

    # Объяснения параллельно — иначе 7 последовательных LLM ≈ минута+.
    reasons = await asyncio.gather(
        *(explain(profile, c.opportunity) for c in candidates)
    )
    created: list[Match] = []
    for cand, reason in zip(candidates, reasons, strict=True):
        m = Match(
            profile_id=profile.id,
            opportunity_id=cand.opportunity.id,
            score=cand.score,
            reason=reason,
            status="new",
        )
        session.add(m)
        created.append(m)
    await session.flush()
    logger.info("Мэтчинг: создано %d новых Match", len(created))
    return created
