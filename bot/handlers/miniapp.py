"""Вход в Mini App из чата: команда /app и кнопка меню.

Только маршрутизация и рендер (docs/services/bot.md). Логика — в `app/`.
Спека Mini App: docs/services/miniapp.md
"""

from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonCommands,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)

from app.config import settings
from app.observability.logging import get_logger

router = Router(name="miniapp")
logger = get_logger("kabi.bot.miniapp")

OPEN_LABEL = "🚀 Открыть Kabi"
APP_COMMAND = BotCommand(command="app", description="Открыть Kabi (приложение)")


def miniapp_url() -> str | None:
    """URL Mini App, если он настроен и пригоден: Telegram принимает только HTTPS."""
    if not settings.miniapp_enabled:
        return None
    url = (settings.miniapp_url or "").strip()
    if not url.startswith("https://"):
        if url:
            logger.warning("miniapp_url отброшен: нужен https:// (%s)", url)
        return None
    return url


def open_app_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=OPEN_LABEL, web_app=WebAppInfo(url=url))]
        ]
    )


async def setup_menu_button(bot: Bot) -> None:
    """Кнопка ≡ рядом с полем ввода открывает Mini App (или возвращает команды)."""
    url = miniapp_url()
    try:
        if url:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="Kabi", web_app=WebAppInfo(url=url))
            )
            logger.info("miniapp_menu_button set url=%s", url)
        else:
            await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    except Exception as exc:  # noqa: BLE001 — сетевой сбой не должен ронять старт
        logger.warning("set_chat_menu_button failed: %s", exc)


@router.message(Command("app"))
async def on_app(message: Message) -> None:
    url = miniapp_url()
    if url is None:
        await message.answer(
            "Приложение пока не подключено — всё работает прямо в чате: "
            "/today, /pitch, /talks, /saved."
        )
        return
    await message.answer(
        "Открой Kabi: подборки, избранное и профиль в одном экране.",
        reply_markup=open_app_keyboard(url),
    )
