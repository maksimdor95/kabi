"""Клавиатуры и рендер карточек. Спека: docs/services/bot.md

Только представление: форматирование текста и кнопки. Никакой логики.
"""

from __future__ import annotations

import re

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
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
    """Меню зависит от приоритета онбординга: job / talk / both."""
    prio = (priorities or "both").lower()
    rows: list[list[KeyboardButton]] = []
    if prio == "job":
        rows.append([KeyboardButton(text=MENU_TODAY), KeyboardButton(text=MENU_SAVED)])
    elif prio == "talk":
        rows.append(
            [KeyboardButton(text=MENU_PITCH), KeyboardButton(text=MENU_DEADLINES)]
        )
        rows.append([KeyboardButton(text=MENU_SAVED)])
    else:
        rows.append([KeyboardButton(text=MENU_TODAY), KeyboardButton(text=MENU_PITCH)])
        rows.append(
            [KeyboardButton(text=MENU_DEADLINES), KeyboardButton(text=MENU_SAVED)]
        )
    rows.append([KeyboardButton(text=MENU_PROFILE)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def menu_for_profile(profile: object | None) -> ReplyKeyboardMarkup:
    """Удобный хелпер: приоритет из ORM Profile или дефолт both."""
    prio = getattr(profile, "priorities", None) if profile is not None else "both"
    return main_menu_keyboard(prio)


def _fmt_salary(salary: dict | None) -> str | None:
    if not salary:
        return None
    lo = salary.get("min")
    hi = salary.get("max")
    cur = salary.get("currency") or "RUB"
    if lo and hi:
        return f"{lo:,}–{hi:,} {cur}".replace(",", " ")
    if lo:
        return f"от {lo:,} {cur}".replace(",", " ")
    if hi:
        return f"до {hi:,} {cur}".replace(",", " ")
    return None


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
# Служебный хвост ingestion (старые записи): «Темы: career_site, avito».
_TOPICS_TAIL_RE = re.compile(
    r"(?:\n|\s)*Темы\s*:\s*[^\n]*$",
    re.I,
)


def _snippet(text: str | None, *, limit: int = 320) -> str | None:
    """Короткая выжимка описания (для карточки без перехода на HH)."""
    if not text:
        return None
    clean = _TOPICS_TAIL_RE.sub("", text)
    clean = _TAG_RE.sub(" ", clean)
    clean = _WS_RE.sub(" ", clean).strip()
    if len(clean) < 40:
        return None
    # отрезать служебные префиксы seed talks
    if clean.lower().startswith("площадка:"):
        return None
    if len(clean) <= limit:
        return clean
    cut = clean[: limit - 1].rsplit(" ", 1)[0]
    return (cut or clean[: limit - 1]).rstrip(".,;:") + "…"


_SOURCE_LABELS: dict[str, str] = {
    "hh.ru": "HeadHunter",
    "superjob.ru": "SuperJob",
    "career.habr.com": "Хабр Карьера",
    "getmatch.ru": "Getmatch",
    "career_yandex": "Яндекс · карьера",
    "career_sber": "Сбер · карьера",
    "career_tbank": "Т-Банк · карьера",
    "career_avito": "Авито · карьера",
    "career_vk": "VK · карьера",
    "career_alfa": "Альфа-Банк · карьера",
    "career_ozon": "Ozon · карьера",
    "career_mts": "МТС · карьера",
    "career_wb": "Wildberries · карьера",
    "career_wildberries": "Wildberries · карьера",
    "career_sites": "Карьерный сайт",
    "tg_jobs": "Telegram",
    "open_cfp": "OpenCFP",
    "cfp_discovery": "Поиск CFP",
    "talk_places_seed": "Каталог площадок",
}

_CAREER_NAMES: dict[str, str] = {
    "yandex": "Яндекс",
    "sber": "Сбер",
    "tbank": "Т-Банк",
    "avito": "Авито",
    "vk": "VK",
    "alfa": "Альфа-Банк",
    "ozon": "Ozon",
    "mts": "МТС",
    "wildberries": "Wildberries",
}


def format_source_label(source: str | None) -> str | None:
    """Человекочитаемый источник (для отладки/логов; на карточке не акцентируем)."""
    if not source:
        return None
    key = source.strip()
    if key in _SOURCE_LABELS:
        return _SOURCE_LABELS[key]
    low = key.lower()
    if low in _SOURCE_LABELS:
        return _SOURCE_LABELS[low]
    if low.startswith("tg_"):
        handle = key[3:].lstrip("@")
        return f"Telegram · {handle}" if handle else "Telegram"
    if low.startswith("career_"):
        site_id = low[len("career_") :]
        name = _CAREER_NAMES.get(site_id, site_id)
        return f"{name} · карьера"
    return key


def format_card(item: DigestItem, *, show_source: bool = False) -> str:
    """Карточка в духе Getmatch: роль → работодатель → ЗП/локация → суть → почему ты."""
    badge = "🎤 " if item.opp_type == "talk" else ""
    lines = [f"<b>{badge}{item.title}</b>"]

    if item.org:
        lines.append(f"<b>🏢 {item.org}</b>")

    salary = _fmt_salary(item.salary)
    if salary:
        lines.append(f"💰 {salary}")

    loc_bits = []
    if item.location:
        loc_bits.append(item.location)
    if item.remote:
        loc_bits.append("удалённо")
    if loc_bits:
        lines.append("📍 " + " · ".join(loc_bits))

    if item.deadline:
        lines.append("⏰ Дедлайн: " + item.deadline.strftime("%d.%m.%Y"))

    snippet = _snippet(item.description)
    if snippet:
        lines.append("")
        lines.append(f"<b>Суть:</b> {snippet}")

    if item.reason:
        lines.append("")
        lines.append(f"<b>Почему ты:</b> {item.reason}")

    if show_source:
        src = format_source_label(item.source)
        if src:
            lines.append(f"<i>{src}</i>")

    if item.url:
        lines.append("")
        label = item.link_label or (
            "Открыть сайт →" if item.opp_type == "talk" else "Открыть вакансию →"
        )
        lines.append(f'<a href="{item.url}">{label}</a>')

    return "\n".join(lines)


def card_keyboard(match_id: str, *, saved: bool = False) -> InlineKeyboardMarkup:
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
                    text="✍️ Сопроводительное",
                    callback_data=f"draft:{match_id}",
                ),
            ],
        ]
    )
