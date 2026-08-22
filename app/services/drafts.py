"""Черновики откликов/заявок под возможность.

Спека: docs/services/drafts.md  (этап M4)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Match, Opportunity, Profile
from app.llm import client as llm
from app.observability.logging import get_logger
from app.services.profile import profile_to_text

logger = get_logger("kabi.drafts")

_SYSTEM = (
    "Ты — персональный карьерный менеджер. Пишешь черновик текста от первого лица "
    "кандидата. Строгие правила:\n"
    "1) Только факты из блока ПРОФИЛЬ — не выдумывай компании, цифры, роли, награды.\n"
    "2) Если факта нет — пропусти или напиши нейтрально без деталей.\n"
    "3) Это черновик: пользователь отправит сам. В конце одной строкой: "
    "«— черновик, отправь сам после правок».\n"
    "4) Язык: русский, деловой тон, без воды и эмодзи."
)


def _opp_block(opp: Opportunity) -> str:
    parts = [
        f"Тип: {opp.type or 'job'}",
        f"Название: {opp.title}",
        f"Организация: {opp.org or '—'}",
        f"Локация: {opp.location or '—'}"
        + (" · удалённо" if opp.remote else ""),
    ]
    if opp.deadline:
        parts.append(f"Дедлайн: {opp.deadline.strftime('%d.%m.%Y')}")
    if opp.url:
        parts.append(f"URL: {opp.url}")
    desc = (opp.description or "")[:1200]
    if desc:
        parts.append(f"Описание:\n{desc}")
    return "\n".join(parts)


async def draft_application(profile: Profile, opportunity: Opportunity) -> str:
    """Черновик отклика / сопроводительного на вакансию (не отправляет)."""
    prompt = (
        "Напиши короткий сопроводительный текст (6–12 предложений) к отклику на вакансию.\n"
        "Структура: кто я и целевая роль → релевантный опыт из профиля → "
        "почему эта вакансия → готовность к следующему шагу.\n\n"
        f"ПРОФИЛЬ:\n{profile_to_text(profile)}\n\n"
        f"ВАКАНСИЯ:\n{_opp_block(opportunity)}\n"
    )
    text = await llm.complete(prompt, system=_SYSTEM, tier="primary", max_tokens=1200)
    return text.strip()


async def draft_cfp_pitch(profile: Profile, opportunity: Opportunity) -> str:
    """Черновик питча / заявки спикера на talk/CFP (не отправляет)."""
    prompt = (
        "Напиши черновик заявки спикера / питча в редакцию или на CFP "
        "(тема, тезис, для кого, почему я, формат — 8–15 предложений или структура с подзаголовками).\n\n"
        f"ПРОФИЛЬ:\n{profile_to_text(profile)}\n\n"
        f"ПЛОЩАДКА / CFP:\n{_opp_block(opportunity)}\n"
    )
    text = await llm.complete(prompt, system=_SYSTEM, tier="primary", max_tokens=1500)
    return text.strip()


async def draft_for_opportunity(profile: Profile, opportunity: Opportunity) -> str:
    """Роутинг: talk → CFP, иначе отклик на job."""
    if (opportunity.type or "job") == "talk":
        logger.info("draft_cfp opp=%s", opportunity.id)
        return await draft_cfp_pitch(profile, opportunity)
    logger.info("draft_application opp=%s", opportunity.id)
    return await draft_application(profile, opportunity)


DraftKind = Literal["cover_letter", "talk_pitch"]


@dataclass(frozen=True)
class DraftResult:
    ok: bool
    error: str = ""  # not_found | forbidden
    kind: DraftKind = "cover_letter"
    text: str = ""


async def draft_for_match(
    session: AsyncSession,
    profile: Profile,
    match_id: str,
) -> DraftResult:
    """Найти свой матч и сгенерировать черновик.

    Владельца проверяем здесь, а не в каналах: бот и Mini App дают один ответ
    (MU-A, docs/services/multiuser.md).
    """
    try:
        mid = uuid.UUID(match_id)
    except ValueError:
        return DraftResult(ok=False, error="not_found")

    row = (
        await session.execute(
            select(Match, Opportunity)
            .join(Opportunity, Opportunity.id == Match.opportunity_id)
            .where(Match.id == mid)
        )
    ).first()
    if row is None:
        return DraftResult(ok=False, error="not_found")

    match, opp = row
    if match.profile_id != profile.id:
        logger.warning(
            "isolation_deny draft match=%s actor_profile=%s owner=%s",
            match_id,
            profile.id,
            match.profile_id,
        )
        return DraftResult(ok=False, error="forbidden")

    is_talk = (opp.type or "job") == "talk"
    text = await draft_for_opportunity(profile, opp)
    return DraftResult(
        ok=True,
        kind="talk_pitch" if is_talk else "cover_letter",
        text=text,
    )
