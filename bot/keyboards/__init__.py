"""Клавиатуры и рендер карточек. Спека: docs/services/bot.md

Только представление: форматирование текста и кнопки. Никакой логики.
"""

from __future__ import annotations

from html import escape

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from app.services.cards import (
    card_approach,
    card_reason,
    card_summary,
    card_title,
    format_salary,
    format_source_label,
)
from app.services.digest import DigestItem

# Пункты главного меню (после онбординга). Подписи — человеческие, не жаргон.
MENU_PROFILE = "👤 Профиль"
MENU_TODAY = "🔎 Вакансии"
MENU_PITCH = "🎙️ СМИ и подкасты"
MENU_SAVED = "🔖 Избранное"
MENU_DEADLINES = "🎤 Конференции"
# Все возможные подписи (чтобы chat-хендлер не перехватывал кнопки).
MAIN_MENU_BUTTONS = (
    MENU_PROFILE,
    MENU_TODAY,
    MENU_PITCH,
    MENU_SAVED,
    MENU_DEADLINES,
    # legacy aliases (если у кого-то залипла старая клавиатура)
    "🎙️ Питч",
    "🎤 CFP",
)


def reply_keyboard(buttons: tuple[str, ...] | list[str]) -> ReplyKeyboardMarkup:
    """Reply-клавиатура: по 2 кнопки в ряд."""
    rows: list[list[KeyboardButton]] = []
    row: list[KeyboardButton] = []
    for label in buttons:
        row.append(KeyboardButton(text=label))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Выбери или напиши…",
    )


def remove_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


def delete_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Да, удалить навсегда",
                    callback_data="profile_del:yes",
                ),
            ],
            [
                InlineKeyboardButton(text="Отмена", callback_data="profile_del:no"),
            ],
        ]
    )


def main_menu_keyboard(priorities: str | None = "both") -> ReplyKeyboardMarkup:
    """Короткое меню (Sprint A): вакансии + избранное + профиль.

    Pitch/talks — командами /pitch /talks, без дубля с Mini App.
    """
    rows: list[list[KeyboardButton]] = [
        [KeyboardButton(text=MENU_TODAY), KeyboardButton(text=MENU_SAVED)],
        [KeyboardButton(text=MENU_PROFILE)],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def menu_for_profile(profile: object | None) -> ReplyKeyboardMarkup:
    """Удобный хелпер: приоритет из ORM Profile или дефолт both."""
    prio = getattr(profile, "priorities", None) if profile is not None else "both"
    return main_menu_keyboard(prio)


def format_card(item: DigestItem, *, show_source: bool = False) -> str:
    """Карточка: шапка + expandable-цитата (Суть/Как зайти + Почему ты)."""
    is_talk = item.opp_type == "talk"
    badge = "🎤 " if is_talk else ""
    title, org = card_title(item)

    lines = [f"<b>{badge}{escape(title)}</b>"]

    if org:
        lines.append(f"<b>🏢 {escape(org)}</b>")

    if is_talk and item.how:
        from app.ingestion.talks.seed_connector import _HOW_LABEL

        how_s = _HOW_LABEL.get(item.how, item.how)
        lines.append(f"Формат: {escape(str(how_s))}")

    salary = format_salary(item.salary)
    if salary:
        lines.append(f"💰 {escape(salary)}")

    loc_bits = []
    if item.location:
        loc_bits.append(item.location)
    if item.remote:
        loc_bits.append("удалённо")
    if loc_bits:
        lines.append("📍 " + " · ".join(escape(b) for b in loc_bits))

    if item.deadline:
        lines.append("⏰ Дедлайн: " + item.deadline.strftime("%d.%m.%Y"))

    quote: list[str] = []
    if is_talk:
        approach = card_approach(item)
        if approach:
            quote.append(f"<b>Как зайти:</b> {escape(approach)}")
    else:
        summary = card_summary(item, title=title)
        if summary:
            quote.append(f"<b>Суть:</b> {escape(summary)}")

    reason = card_reason(item)
    if reason:
        # буллеты многострочные — escape по строкам, переносы сохранить
        reason_html = "\n".join(escape(line) for line in reason.splitlines())
        quote.append(f"<b>Почему ты:</b>\n{reason_html}")

    if quote:
        lines.append("")
        lines.append("<blockquote expandable>" + "\n\n".join(quote) + "</blockquote>")

    if show_source:
        src = format_source_label(item.source)
        if src:
            lines.append(f"<i>{escape(src)}</i>")

    if item.url and item.link_label:
        lines.append("")
        lines.append(f'<a href="{escape(item.url, quote=True)}">{escape(item.link_label)}</a>')

    return "\n".join(lines)


def card_keyboard(
    match_id: str,
    *,
    saved: bool = False,
    draft_label: str = "✍️ Сопроводительное",
) -> InlineKeyboardMarkup:
    def cb(action: str) -> str:
        return f"fb:{action}:{match_id}"

    save_btn = (
        InlineKeyboardButton(text="🗑️ Убрать", callback_data=cb("unsave"))
        if saved
        else InlineKeyboardButton(text="🔖 Избранное", callback_data=cb("save"))
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👍 Интересно", callback_data=cb("up")),
                InlineKeyboardButton(text="👎 Мимо", callback_data=cb("down")),
            ],
            [
                save_btn,
                InlineKeyboardButton(text="🙈 Скрыть", callback_data=cb("hide")),
            ],
            [
                # draft: — отдельный хендлер (не fb:), иначе «Уже неактуально».
                InlineKeyboardButton(
                    text=draft_label,
                    callback_data=f"draft:{match_id}",
                ),
            ],
        ]
    )
