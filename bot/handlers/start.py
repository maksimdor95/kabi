"""Хендлер /start. Спека: docs/services/bot.md"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.db.session import get_session
from app.services import dialogue_agent
from app.services import profile as profile_service
from app.services.onboarding import STEPS
from bot.keyboards import menu_for_profile, remove_keyboard, reply_keyboard

router = Router(name="start")


@router.message(CommandStart())
async def on_start(message: Message) -> None:
    async with get_session() as session:
        user = await profile_service.get_or_create_user(session, message.from_user.id)
        profile = await profile_service.get_profile(session, user.id)
        if profile is not None:
            from app.services import analytics

            await analytics.emit(
                session,
                name="session_started",
                profile_id=profile.id,
                props={"channel": "bot"},
            )
        await session.commit()

    if profile is None:
        await message.answer(
            "Привет! Я твой персональный карьерный менеджер.\n\n"
            "Начнём с профиля — любым способом:\n"
            "1) резюме PDF или DOCX\n"
            "2) текст: роли и опыт парой предложений\n"
            "3) ссылка HH / LinkedIn (/in/…)\n\n"
            "Потом коротко уточню фокус и принесу вакансии.\n"
            "/profile — что уже знаю о тебе.",
            reply_markup=remove_keyboard(),
        )
        return

    if dialogue_agent.is_onboarding_complete(profile):
        roles = ", ".join((profile.roles or [])[:3]) or "профиль"
        await message.answer(
            f"Снова привет! Профиль уже собран ({roles}).\n\n"
            "Команды: /today · /profile · /schedule · /saved\n"
            "Новое резюме — обновлю без повторных вопросов.\n"
            "Онбординг заново — «начать заново».",
            reply_markup=menu_for_profile(profile),
        )
        return

    if 0 <= profile.onboarding_step < len(STEPS):
        step = STEPS[profile.onboarding_step]
        await message.answer(
            "Продолжим с того места, где остановились.\n\n" + step.question,
            reply_markup=reply_keyboard(step.buttons) if step.buttons else remove_keyboard(),
        )
        return

    await message.answer(
        "Пришли резюме, текст с ролями или ссылку HH/LinkedIn — начнём.",
        reply_markup=remove_keyboard(),
    )
