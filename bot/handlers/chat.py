"""Хендлер свободного текста (онбординг / диалог). Спека: docs/services/bot.md"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from app.db.session import get_session
from app.services import dialogue_agent
from app.services import profile as profile_service
from app.services import schedule as schedule_service
from bot.keyboards import (
    MAIN_MENU_BUTTONS,
    menu_for_profile,
    remove_keyboard,
    reply_keyboard,
)

router = Router(name="chat")


@router.message(F.text, ~F.text.startswith("/"), ~F.text.in_(MAIN_MENU_BUTTONS))
async def on_text(message: Message) -> None:
    """Текст без /команд и без пунктов меню."""
    text = message.text or ""

    async with get_session() as session:
        user = await profile_service.get_or_create_user(session, message.from_user.id)
        profile = await profile_service.get_profile(session, user.id)

        # Расписание — только после онбординга (все шаги STEPS), явные фразы.
        mid_onboarding = bool(
            profile is not None and not dialogue_agent.is_onboarding_complete(profile)
        )
        if profile is not None and not mid_onboarding:
            updated = schedule_service.parse_schedule_command(text, profile.digest_schedule)
            if updated is not None:
                profile.digest_schedule = updated
                await session.commit()
                await message.answer(
                    "Обновил расписание.\n\n" + schedule_service.format_schedule(updated),
                    reply_markup=menu_for_profile(profile),
                )
                return
            low = text.strip().lower()
            if low in {"расписание", "расписание рассылок"}:
                await session.commit()
                await message.answer(
                    schedule_service.format_schedule(profile.digest_schedule),
                    reply_markup=menu_for_profile(profile),
                )
                return

        reply = await dialogue_agent.handle_message(session, user, text)
        await session.commit()
        profile = await profile_service.get_profile(session, user.id)

    if reply.finished:
        markup = menu_for_profile(profile)
    elif reply.buttons:
        markup = reply_keyboard(reply.buttons)
    elif reply.remove_keyboard:
        markup = remove_keyboard()
    else:
        markup = None
    await message.answer(reply.text, reply_markup=markup)
