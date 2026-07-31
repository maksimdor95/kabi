"""Хендлер /start. Спека: docs/services/bot.md"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.db.session import get_session
from app.services import dialogue_agent
from app.services import profile as profile_service
from app.services.onboarding import STEPS
from bot.keyboards import main_menu_keyboard, menu_for_profile, remove_keyboard, reply_keyboard

router = Router(name="start")


@router.message(CommandStart())
async def on_start(message: Message) -> None:
    async with get_session() as session:
        user = await profile_service.get_or_create_user(session, message.from_user.id)
        profile = await profile_service.get_profile(session, user.id)
        await session.commit()

    if profile is None:
        await message.answer(
            "Привет! Я твой персональный карьерный менеджер. 🎯\n\n"
            "Чтобы собрать первоначальный профиль, пришли всё полезное:\n"
            "1) резюме (PDF или DOCX) — обязательно\n"
            "2) потом ссылки: LinkedIn, HH, личный сайт с публикациями/эфирами, "
            "записи выступлений\n\n"
            "Дальше я сам дособеру картину и буду искать вакансии и приглашения.\n"
            "Профиль всегда можно открыть: /profile",
            reply_markup=remove_keyboard(),
        )
        return

    if dialogue_agent.is_onboarding_complete(profile):
        roles = ", ".join((profile.roles or [])[:3]) or "профиль"
        await message.answer(
            f"Снова привет! Профиль уже собран ({roles}).\n\n"
            "Меню внизу зависит от приоритета (Работа / Выступления / Оба).\n"
            "Команды: /profile /today /pitch /talks /saved /schedule\n\n"
            "Новое резюме — обновлю без повторных вопросов.\n"
            "Ссылки (сайт, LinkedIn) можно кидать в чат в любой момент.\n"
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
        "Пришли резюме (PDF или DOCX) — начнём.",
        reply_markup=remove_keyboard(),
    )
