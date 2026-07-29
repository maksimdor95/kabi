"""Обработка реакций на карточки подборки (👍/👎/скрыть/сохранить).

Пишет Feedback, обновляет Match.status; на 👍/👎 сдвигает Profile.embedding (M4).
Спека: docs/services/feedback.md
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Feedback, Match, Opportunity, Profile
from app.observability.logging import get_logger
from app.services.digest import DigestItem

logger = get_logger("kabi.feedback")

_ALPHA_UP = 0.15
_ALPHA_DOWN = 0.20

# реакция → новый статус Match (save обрабатывается отдельно — toggle)
_REACTION_STATUS = {
    "up": "liked",
    "down": "disliked",
    "hide": "hidden",
    "unsave": "new",
}


@dataclass(frozen=True)
class ReactionResult:
    ok: bool
    effect: str = ""  # saved | unsaved | liked | disliked | hidden | …
    learned: bool = False


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm < 1e-12:
        return list(vec)
    return [x / norm for x in vec]


def blend_embedding(
    base: list[float],
    delta: list[float],
    *,
    sign: int,
    alpha: float,
) -> list[float]:
    """Сдвинуть base к (+1) или от (-1) delta и L2-нормализовать.

    sign: +1 для 👍, -1 для 👎.
    """
    if len(base) != len(delta):
        raise ValueError(f"dim mismatch: base={len(base)} delta={len(delta)}")
    if sign not in (1, -1):
        raise ValueError("sign must be +1 or -1")
    mixed = [b + sign * alpha * d for b, d in zip(base, delta, strict=True)]
    return _l2_normalize(mixed)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Для тестов / диагностики."""
    if len(a) != len(b):
        raise ValueError("dim mismatch")
    an = _l2_normalize(a)
    bn = _l2_normalize(b)
    return sum(x * y for x, y in zip(an, bn, strict=True))


async def _apply_embedding_learning(
    session: AsyncSession, match: Match, effect: str
) -> bool:
    """Сдвинуть эмбеддинг профиля. True если применили."""
    if effect not in {"up", "liked", "down", "disliked"}:
        return False
    is_up = effect in {"up", "liked"}

    profile = await session.get(Profile, match.profile_id)
    opp = await session.get(Opportunity, match.opportunity_id)
    if profile is None or opp is None:
        return False

    if profile.embedding is None:
        from app.services import profile as profile_service

        try:
            await profile_service.compute_embedding(session, profile)
        except Exception:  # noqa: BLE001
            logger.warning("feedback_learn skip: cannot embed profile=%s", profile.id)
            return False

    if profile.embedding is None:
        return False
    if opp.embedding is None:
        logger.warning("feedback_learn skip: opp=%s has no embedding", opp.id)
        return False

    base = list(profile.embedding)
    delta = list(opp.embedding)
    try:
        profile.embedding = blend_embedding(
            base,
            delta,
            sign=1 if is_up else -1,
            alpha=_ALPHA_UP if is_up else _ALPHA_DOWN,
        )
    except ValueError as exc:
        logger.warning("feedback_learn blend failed: %s", exc)
        return False

    await session.flush()
    logger.info(
        "feedback_learn profile=%s effect=%s alpha=%.2f",
        profile.id,
        "up" if is_up else "down",
        _ALPHA_UP if is_up else _ALPHA_DOWN,
    )
    return True


async def record_reaction(session: AsyncSession, match_id: str, reaction: str) -> ReactionResult:
    """Сохранить реакцию. save на уже saved → снять с избранного. 👍/👎 → blend emb."""
    if reaction not in {"up", "down", "hide", "save", "unsave"}:
        return ReactionResult(ok=False)
    try:
        mid = uuid.UUID(match_id)
    except ValueError:
        return ReactionResult(ok=False)

    match = await session.get(Match, mid)
    if match is None:
        return ReactionResult(ok=False)

    if reaction == "save":
        if match.status == "saved":
            reaction = "unsave"
            match.status = "new"
            effect = "unsaved"
        else:
            match.status = "saved"
            effect = "saved"
    elif reaction == "unsave":
        match.status = "new"
        effect = "unsaved"
    else:
        match.status = _REACTION_STATUS[reaction]
        effect = reaction

    session.add(Feedback(match_id=mid, reaction=reaction))
    await session.flush()

    learned = False
    if effect in {"up", "down"}:
        learned = await _apply_embedding_learning(session, match, effect)

    logger.info(
        "feedback match=%s reaction=%s effect=%s learned=%s",
        match_id,
        reaction,
        effect,
        learned,
    )
    return ReactionResult(ok=True, effect=effect, learned=learned)


async def list_saved(session: AsyncSession, profile: Profile) -> list[DigestItem]:
    """Сохранённые в избранное вакансии (Match.status=saved)."""
    rows = (
        await session.execute(
            select(Match, Opportunity)
            .join(Opportunity, Opportunity.id == Match.opportunity_id)
            .where(Match.profile_id == profile.id, Match.status == "saved")
            .order_by(Match.created_at.desc())
        )
    ).all()
    items: list[DigestItem] = []
    for match, opp in rows:
        items.append(
            DigestItem(
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
            )
        )
    return items
