"""Точка входа Telegram-бота.

Спека: docs/services/bot.md
Правило: здесь только маршрутизация и рендер, бизнес-логика — в app/.
"""

from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher

from app.config import settings
from app.db.session import init_db
from app.observability.logging import get_logger
from app.scheduler import start_scheduler
from bot.handlers import chat, cv, digest, profile, start

logger = get_logger("kabi.bot")


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(start.router)
    dp.include_router(cv.router)
    dp.include_router(profile.router)  # /profile + меню
    dp.include_router(digest.router)  # /today /saved + колбэки
    dp.include_router(chat.router)  # текст — последним
    return dp


async def main() -> None:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан (.env)")
    await init_db()
    bot = Bot(token=settings.telegram_bot_token)
    from bot.handlers.profile import BOT_COMMANDS

    try:
        await bot.set_my_commands(BOT_COMMANDS)
    except Exception as exc:  # noqa: BLE001 — не блокируем старт при сетевых сбоях
        logger.warning("set_my_commands failed: %s", exc)
    dp = build_dispatcher()
    start_scheduler(bot)
    logger.info("bot_starting")
    await dp.start_polling(bot)


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
