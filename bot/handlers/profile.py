"""Просмотр профиля, расписание и удаление. Спека: docs/services/bot.md"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import BotCommand, CallbackQuery, Message

from app.db.session import get_session
from app.observability.logging import get_logger
from app.services import profile as profile_service
from app.services import schedule as schedule_service
from bot.keyboards import (
    MAIN_MENU_BUTTONS,
    MENU_DEADLINES,
    MENU_PITCH,
    MENU_PROFILE,
    MENU_SAVED,
    MENU_TODAY,
    delete_confirm_keyboard,
    menu_for_profile,
    remove_keyboard,
)

router = Router(name="profile")
logger = get_logger("kabi.bot.profile")

BOT_COMMANDS = [
    BotCommand(command="start", description="Старт / статус"),
    BotCommand(command="profile", description="Что менеджер знает о тебе"),
    BotCommand(command="today", description="Вакансии"),
    BotCommand(command="pitch", description="СМИ и подкасты"),
    BotCommand(command="talks", description="Конференции со сроком подачи"),
    BotCommand(command="saved", description="Избранное"),
    BotCommand(command="schedule", description="Расписание рассылок"),
    BotCommand(command="delete", description="Удалить профиль навсегда"),
]


async def send_profile_card(message: Message) -> None:
    async with get_session() as session:
        user = await profile_service.get_or_create_user(session, message.from_user.id)
        profile = await profile_service.get_profile(session, user.id)
        await session.commit()

    if profile is None:
        await message.answer(
            "Профиля ещё нет. Пришли резюме (PDF или DOCX) — начнём.",
            reply_markup=remove_keyboard(),
        )
        return

    await message.answer(
        profile_service.format_profile_card(profile),
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=menu_for_profile(profile),
    )


@router.message(Command("profile"))
async def on_profile(message: Message) -> None:
    await send_profile_card(message)


@router.message(Command("delete", "delete_profile"))
async def on_delete_ask(message: Message) -> None:
    """Запрос подтверждения перед полным удалением."""
    async with get_session() as session:
        user = await profile_service.get_or_create_user(session, message.from_user.id)
        profile = await profile_service.get_profile(session, user.id)
        await session.commit()

    if profile is None:
        await message.answer(
            "Профиля нет — удалять нечего. Пришли резюме, когда будешь готов.",
            reply_markup=remove_keyboard(),
        )
        return

    await message.answer(
        "Удалю профиль, мэтчи, избранное и файл резюме — безвозвратно.\n"
        "Вакансии и площадки в общей базе останутся.\n\n"
        "Это не «начать заново» (тот только сбрасывает онбординг).\n"
        "Подтверди:",
        reply_markup=delete_confirm_keyboard(),
    )


@router.callback_query(F.data == "profile_del:no")
async def on_delete_cancel(callback: CallbackQuery) -> None:
    await callback.answer("Отменил")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        "Ок, профиль на месте.",
        reply_markup=menu_for_profile(None),
    )


@router.callback_query(F.data == "profile_del:yes")
async def on_delete_confirm(callback: CallbackQuery) -> None:
    tg_id = callback.from_user.id if callback.from_user else None
    if tg_id is None:
        await callback.answer("Не понял пользователя")
        return

    async with get_session() as session:
        result = await profile_service.delete_account(session, tg_id)
        await session.commit()

    await callback.answer("Удалено" if result.deleted else "Уже пусто")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    if not result.deleted:
        await callback.message.answer(
            "Аккаунта уже нет. /start — начать с нуля.",
            reply_markup=remove_keyboard(),
        )
        return

    logger.info("profile_deleted tg=%s matches=%s", tg_id, result.matches_removed)
    await callback.message.answer(
        "Профиль удалён. Чтобы начать снова — пришли резюме или /start.",
        reply_markup=remove_keyboard(),
    )


@router.message(Command("schedule"))
async def on_schedule(message: Message) -> None:
    """Показать или изменить расписание рассылок."""
    text = (message.text or "").strip()
    # «/schedule вакансии будни 9:00»
    parts = text.split(maxsplit=1)
    tail = parts[1] if len(parts) > 1 else ""

    async with get_session() as session:
        user = await profile_service.get_or_create_user(session, message.from_user.id)
        profile = await profile_service.get_profile(session, user.id)
        if profile is None:
            await session.commit()
            await message.answer(
                "Сначала загрузи резюме и пройди онбординг.",
                reply_markup=remove_keyboard(),
            )
            return

        if tail:
            updated = schedule_service.parse_schedule_command(tail, profile.digest_schedule)
            if updated is None:
                await session.commit()
                await message.answer(
                    "Не понял. Пример: «мониторинг вкл», «вакансии будни 9:00», "
                    "«режим свежие», «тихие часы 23:00-8:00».\n\n"
                    + schedule_service.format_schedule(profile.digest_schedule),
                    reply_markup=menu_for_profile(profile),
                )
                return
            profile.digest_schedule = updated
            await session.commit()
            await message.answer(
                "Обновил.\n\n" + schedule_service.format_schedule(updated),
                reply_markup=menu_for_profile(profile),
            )
            return

        await session.commit()
        await message.answer(
            schedule_service.format_schedule(profile.digest_schedule),
            reply_markup=menu_for_profile(profile),
        )


@router.message(F.text == MENU_PROFILE)
async def on_menu_profile(message: Message) -> None:
    await send_profile_card(message)


@router.message(F.text.in_(MAIN_MENU_BUTTONS))
async def on_menu_other(message: Message) -> None:
    """Маршрутизация пунктов меню на команды."""
    text = message.text
    if text == MENU_TODAY:
        from bot.handlers.digest import on_today

        await on_today(message)
        return
    if text in (MENU_PITCH, "🎙️ Питч"):
        from bot.handlers.digest import on_pitch

        await on_pitch(message)
        return
    if text == MENU_SAVED:
        from bot.handlers.digest import on_saved

        await on_saved(message)
        return
    if text in (MENU_DEADLINES, "🎤 CFP"):
        from bot.handlers.digest import on_deadlines

        await on_deadlines(message)
        return
