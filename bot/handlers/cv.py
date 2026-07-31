"""Хендлер загрузки CV. Спека: docs/services/bot.md"""

from __future__ import annotations

from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.types import Message

from app.db.session import get_session
from app.observability.logging import get_logger
from app.services import cv_parser, dialogue_agent
from app.services import profile as profile_service
from app.services.dialogue_agent import AgentReply
from app.services.onboarding import extract_urls
from bot.keyboards import main_menu_keyboard, menu_for_profile, reply_keyboard

router = Router(name="cv")
logger = get_logger("kabi.bot.cv")

_UPLOADS = Path("uploads")
_ALLOWED = {".pdf", ".docx"}

_PROFILE_READY = "Обновил профиль из резюме."


def _merge_after_cv(reply: AgentReply) -> str:
    """Одно сообщение: короткий ack по CV + следующий шаг (без второго «смотри /profile»)."""
    body = reply.text.strip()
    if body.startswith(_PROFILE_READY):
        return body
    return f"{_PROFILE_READY}\n\n{body}" if body else _PROFILE_READY


@router.message(F.document)
async def on_document(message: Message, bot: Bot) -> None:
    doc = message.document
    suffix = Path(doc.file_name or "").suffix.lower()
    if suffix not in _ALLOWED:
        await message.answer("Нужен файл резюме в формате PDF или DOCX.")
        return

    _UPLOADS.mkdir(exist_ok=True)
    dest = _UPLOADS / f"{message.from_user.id}_{doc.file_name}"
    await bot.download(doc, destination=dest)
    await message.answer("Получил резюме, изучаю… 📄")

    try:
        draft = await cv_parser.parse_cv(str(dest))
    except Exception as exc:  # noqa: BLE001 — покажем пользователю дружелюбно
        logger.exception("cv_parse_failed")
        await message.answer(f"Не смог разобрать резюме: {exc}")
        return

    caption = (message.caption or "").strip()

    async with get_session() as session:
        user = await profile_service.get_or_create_user(session, message.from_user.id)
        existing = await profile_service.get_profile(session, user.id)
        was_complete = bool(existing and dialogue_agent.is_onboarding_complete(existing))
        # Любой незавершённый онбординг (включая шаг 0 — ссылки): не сбрасывать.
        mid_onboarding = bool(existing and not was_complete)

        profile = await profile_service.apply_cv_draft(
            session, user.id, draft, raw_cv_ref=str(dest)
        )

        if was_complete:
            extra = ""
            if caption and extract_urls(caption) and profile.enrichment_consent:
                reply = await dialogue_agent.handle_message(session, user, caption)
                extra = "\n\n" + reply.text
            await session.commit()
            await message.answer(
                "Обновил профиль из резюме (онбординг не сбрасываю)."
                f"{extra}\n\n"
                "Смотри /today · /pitch · /talks · /saved\n"
                "Онбординг заново — «начать заново».",
                reply_markup=menu_for_profile(profile),
            )
            return

        if mid_onboarding:
            # Не переспрашиваем тот же шаг и не зовём start_onboarding
            # (иначе сброс ссылок + «бубль» профиль/ссылки/приоритет).
            if caption and extract_urls(caption):
                reply = await dialogue_agent.handle_message(session, user, caption)
                await session.commit()
                markup = reply_keyboard(reply.buttons) if reply.buttons else None
                if reply.remove_keyboard:
                    markup = menu_for_profile(profile)
                await message.answer(_merge_after_cv(reply), reply_markup=markup)
                return
            await session.commit()
            await message.answer(_PROFILE_READY)
            return

        await dialogue_agent.start_onboarding(session, profile)

        if caption and extract_urls(caption):
            reply = await dialogue_agent.handle_message(session, user, caption)
            await session.commit()
            markup = reply_keyboard(reply.buttons) if reply.buttons else None
            if reply.finished or reply.remove_keyboard:
                markup = menu_for_profile(profile)
            await message.answer(_merge_after_cv(reply), reply_markup=markup)
            return

        reply = await dialogue_agent.continue_onboarding(profile)
        await session.commit()

    markup = reply_keyboard(reply.buttons) if reply.buttons else None
    await message.answer(_merge_after_cv(reply), reply_markup=markup)
