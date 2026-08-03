"""Хендлеры подборки: команда /today и реакции на карточки.

Только маршрутизация и рендер (см. docs/services/bot.md). Вся логика —
в app/services/{digest,feedback,drafts}.py.
"""

from __future__ import annotations

import uuid

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from app.db.models import Match, Opportunity, Profile
from app.db.session import get_session
from app.observability.logging import get_logger
from app.services import digest as digest_service
from app.services import drafts as drafts_service
from app.services import feedback as feedback_service
from app.services import profile as profile_service
from app.services.onboarding import STEPS
from bot.keyboards import (
    card_keyboard,
    format_card,
    menu_for_profile,
    remove_keyboard,
    reply_keyboard,
)

router = Router(name="digest")
logger = get_logger("kabi.bot.digest")

_REACTION_ACK = {
    "up": "👍 Запомнил, буду искать похожее.",
    "down": "👎 Понял, меньше такого.",
    "save": "🔖 В избранном. Смотреть: /saved",
    "saved": "🔖 В избранном. Смотреть: /saved",
    "unsave": "Убрал из избранного.",
    "unsaved": "Убрал из избранного.",
    "hide": "🙈 Скрыл — больше не покажу.",
    "hidden": "🙈 Скрыл — больше не покажу.",
    "liked": "👍 Запомнил, буду искать похожее.",
    "disliked": "👎 Понял, меньше такого.",
}


async def _answer_not_ready(message: Message, profile: Profile | None) -> None:
    """Отказ без ложного «собираю…»: сразу что не хватает + текущий шаг."""
    if profile is None:
        await message.answer(
            "Сначала загрузи резюме (PDF/DOCX) и пройди короткий онбординг 🙌",
            reply_markup=remove_keyboard(),
        )
        return

    step_idx = profile.onboarding_step or 0
    if 0 <= step_idx < len(STEPS):
        step = STEPS[step_idx]
        await message.answer(
            "Профиль ещё не готов к подбору — допиши ответы в онбординге.\n\n"
            + step.question,
            reply_markup=(
                reply_keyboard(step.buttons) if step.buttons else remove_keyboard()
            ),
        )
        return

    await message.answer(
        "Профиль ещё не готов к подбору. Открой /profile — чего не хватает, "
        "или допиши зарплату / красные флаги в чат.",
        reply_markup=menu_for_profile(profile),
    )


@router.message(Command("today"))
async def on_today(message: Message) -> None:
    logger.info("cmd_today from tg=%s", message.from_user.id if message.from_user else None)
    async with get_session() as session:
        user = await profile_service.get_or_create_user(session, message.from_user.id)
        profile = await profile_service.get_profile(session, user.id)
        if profile is None or not profile.ready_for_matching:
            await session.commit()
            await _answer_not_ready(message, profile)
            return
        await message.answer(
            "Собираю свежие вакансии… 🔎",
            reply_markup=menu_for_profile(profile),
        )
        items = await digest_service.build_digest(session, profile, scope="jobs")
        await session.commit()

    if not items:
        await message.answer(
            "Свежих подходящих вакансий пока не нашёл. "
            "СМИ/подкасты — /pitch, конференции — /talks."
        )
        return

    await message.answer(f"Вакансии — {len(items)}:")
    for item in items:
        await message.answer(
            format_card(item),
            reply_markup=card_keyboard(item.match_id),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


@router.message(Command("pitch"))
async def on_pitch(message: Message) -> None:
    """СМИ и подкасты для питча — без выдуманных дедлайнов."""
    logger.info("cmd_pitch from tg=%s", message.from_user.id if message.from_user else None)
    async with get_session() as session:
        user = await profile_service.get_or_create_user(session, message.from_user.id)
        profile = await profile_service.get_profile(session, user.id)
        if profile is None or not profile.ready_for_matching:
            await session.commit()
            await _answer_not_ready(message, profile)
            return
        await message.answer(
            "Подбираю СМИ и подкасты… 🎙️",
            reply_markup=menu_for_profile(profile),
        )
        items = await digest_service.build_digest(session, profile, scope="pitch")
        await session.commit()

    if not items:
        await message.answer(
            "Пока нет подходящих СМИ/подкастов под твои темы. "
            "Пока нет подходящих СМИ/подкастов под твои темы. "
            "Конференции со сроком подачи — /talks, вакансии — /today."
        )
        return

    await message.answer(f"СМИ и подкасты — {len(items)}:")
    for item in items:
        await message.answer(
            format_card(item),
            reply_markup=card_keyboard(item.match_id),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


@router.message(Command("saved"))
async def on_saved(message: Message) -> None:
    logger.info("cmd_saved from tg=%s", message.from_user.id if message.from_user else None)
    async with get_session() as session:
        user = await profile_service.get_or_create_user(session, message.from_user.id)
        profile = await profile_service.get_profile(session, user.id)
        if profile is None:
            await session.commit()
            await message.answer("Сначала загрузи резюме и пройди онбординг.")
            return
        items = await feedback_service.list_saved(session, profile)
        await session.commit()

    if not items:
        await message.answer(
            "В избранном пока пусто. В /today нажми «🔖 Избранное» на карточке. "
            "Убрать — в /saved кнопка «🗑️ Убрать»."
        )
        return

    await message.answer(f"Избранное — {len(items)}:")
    for item in items:
        await message.answer(
            format_card(item),
            reply_markup=card_keyboard(item.match_id, saved=True),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


@router.message(Command("talks", "deadlines"))
async def on_talks(message: Message) -> None:
    """Конференции со сроком подачи. /deadlines — тихий алиас (не в меню команд)."""
    from app.services import deadlines as deadlines_service

    logger.info(
        "cmd_talks from tg=%s", message.from_user.id if message.from_user else None
    )
    async with get_session() as session:
        user = await profile_service.get_or_create_user(session, message.from_user.id)
        profile = await profile_service.get_profile(session, user.id)
        if profile is None:
            await session.commit()
            await message.answer("Сначала загрузи резюме и пройди онбординг.")
            return
        # Без live HTTP по страницам заявок: данные уже в БД (seed + ночной scheduler).
        items = await deadlines_service.list_upcoming(session, within_days=60)
        await session.commit()

    await message.answer(
        deadlines_service.format_deadlines_message(items),
        disable_web_page_preview=True,
        reply_markup=menu_for_profile(profile),
    )


# Алиас для меню / внутренних импортов.
on_deadlines = on_talks


@router.callback_query(F.data.startswith("fb:"))
async def on_feedback(callback: CallbackQuery) -> None:
    try:
        _, reaction, match_id = callback.data.split(":", 2)
    except ValueError:
        await callback.answer("Не понял реакцию")
        return

    async with get_session() as session:
        result = await feedback_service.record_reaction(session, match_id, reaction)
        await session.commit()

    if not result.ok:
        await callback.answer("Уже неактуально")
        return

    ack = _REACTION_ACK.get(result.effect) or _REACTION_ACK.get(reaction, "Готово")
    if result.learned:
        ack = f"{ack} Учёл для следующих подборок."
    await callback.answer(ack[:200])

    if result.effect in ("unsaved", "hidden", "hide"):
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        if result.effect in ("hidden", "hide"):
            try:
                await callback.message.edit_text(
                    "🙈 <i>Скрыто — больше не покажу эту вакансию.</i>",
                    parse_mode="HTML",
                )
            except Exception:
                pass
        return

    if result.effect == "saved":
        try:
            await callback.message.edit_reply_markup(
                reply_markup=card_keyboard(match_id, saved=True)
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("draft:"))
async def on_draft(callback: CallbackQuery) -> None:
    match_id = (callback.data or "").removeprefix("draft:").strip()
    if not match_id:
        await callback.answer("Не понял карточку")
        return

    await callback.answer("Готовлю сопроводительное…")
    async with get_session() as session:
        try:
            mid = uuid.UUID(match_id)
        except ValueError:
            await callback.message.answer("Карточка устарела.")
            return

        row = (
            await session.execute(
                select(Match, Opportunity)
                .join(Opportunity, Opportunity.id == Match.opportunity_id)
                .where(Match.id == mid)
            )
        ).first()
        if row is None:
            await callback.message.answer("Карточка устарела.")
            return
        match, opp = row
        # match.profile_id — это Profile.id, а не user_id: берём напрямую.
        profile = await session.get(Profile, match.profile_id)
        if profile is None:
            await callback.message.answer("Сначала собери профиль.")
            return
        try:
            text = await drafts_service.draft_for_opportunity(profile, opp)
        except Exception as exc:  # noqa: BLE001
            logger.exception("draft_failed match=%s", match_id)
            await callback.message.answer(f"Не смог набросать черновик: {exc}")
            await session.commit()
            return
        await session.commit()

    if (opp.type or "") == "talk":
        header = "<b>Черновик заявки / питча</b> — проверь и отправь сам:"
    else:
        header = "<b>Сопроводительное письмо</b> — проверь и отправь сам:"
    await callback.message.answer(
        f"{header}\n\n{text}",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
