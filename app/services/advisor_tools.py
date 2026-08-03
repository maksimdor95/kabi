"""Инструменты советника (M9): профиль / снимок / живой digest / расписание.

Спека: docs/services/dialogue-agent.md
Детерминированный роутер интентов — без native function calling.
Живой ingest — только по явной просьбе (refresh_*), иначе кэш (do_ingest=False).
"""

from __future__ import annotations

import re
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Profile
from app.services import digest as digest_service
from app.services import profile as profile_service
from app.services import schedule as schedule_service

ToolName = Literal[
    "get_profile",
    "get_job_snapshot",
    "get_talk_snapshot",
    "refresh_jobs",
    "refresh_talks",
    "get_schedule",
]

_TOOL_PATTERNS: list[tuple[ToolName, re.Pattern[str]]] = [
    (
        "get_profile",
        re.compile(
            r"(профил\w*|что ты (обо мне|знаешь)|что знаешь обо мне|"
            r"мои (навыки|роли|ожидания)|расскажи обо мне)",
            re.I,
        ),
    ),
    (
        "refresh_jobs",
        re.compile(
            r"((найди|поищи|обнови|запусти|свеж\w*|живой поиск|"
            r"поискн\w*|пересобер\w*).{0,40}(ваканси\w*|работ)|"
            r"(ваканси\w*|работ).{0,20}(найди|поищи|обнови|свеж))",
            re.I,
        ),
    ),
    (
        "refresh_talks",
        re.compile(
            r"((найди|поищи|обнови|запусти|свеж\w*|живой поиск|"
            r"пересобер\w*).{0,40}(выступлен\w*|конференц\w*|cfp|питч)|"
            r"(выступлен\w*|конференц\w*|cfp).{0,20}(найди|поищи|обнови|свеж))",
            re.I,
        ),
    ),
    (
        "get_job_snapshot",
        re.compile(
            r"(ваканси\w*|работ[аыуе]|джоб|подборк\w* работ|"
            r"что (нашёл|нашел|есть) по работ|"
            r"/today|сегодняшн\w* вакан)",
            re.I,
        ),
    ),
    (
        "get_talk_snapshot",
        re.compile(
            r"(выступлен\w*|конференц\w*|cfp|питч|подкаст\w*|"
            r"/talks|/pitch|куда податься|куда выступить)",
            re.I,
        ),
    ),
    (
        "get_schedule",
        re.compile(
            r"(расписан\w*|когда (присыл\w*|шлёшь|пишешь|приходит)|"
            r"тихие часы|мониторинг|как часто)",
            re.I,
        ),
    ),
]


def select_tools(text: str) -> list[ToolName]:
    """Выбрать tools по тексту (порядок стабильный). Live вытесняет snapshot."""
    found: list[ToolName] = []
    for name, pat in _TOOL_PATTERNS:
        if pat.search(text) and name not in found:
            found.append(name)

    if "refresh_jobs" in found and "get_job_snapshot" in found:
        found.remove("get_job_snapshot")
    if "refresh_talks" in found and "get_talk_snapshot" in found:
        found.remove("get_talk_snapshot")
    return found


def _plain_profile(profile: Profile) -> str:
    card = profile_service.format_profile_card(profile)
    return re.sub(r"</?b>", "", card)


def _fmt_items(items: list, *, header: str, empty: str, footer: str) -> str:
    if not items:
        return empty
    lines = [header]
    for i, it in enumerate(items, 1):
        org = f" · {it.org}" if it.org else ""
        dl = ""
        if getattr(it, "deadline", None):
            dl = f", дедлайн {it.deadline.date().isoformat()}"
        reason = f" — {it.reason}" if it.reason else ""
        lines.append(f"{i}. {it.title}{org}{dl}{reason}")
        if it.url:
            lines.append(f"   {it.url}")
    lines.append(footer)
    return "\n".join(lines)


async def _job_digest(
    session: AsyncSession, profile: Profile, *, live: bool
) -> str:
    items = await digest_service.build_digest(
        session,
        profile,
        scope="jobs",
        do_ingest=live,
        limit=5 if live else 3,
    )
    if live:
        return _fmt_items(
            items,
            header="Живой поиск вакансий (ingest выполнен):",
            empty=(
                "Живой поиск завершён, подходящих вакансий нет. "
                "Не выдумывай позиции. Можно позже /today."
            ),
            footer="Команда /today — то же самое из меню.",
        )
    return _fmt_items(
        items,
        header="Снимок вакансий из кэша (без нового ingest):",
        empty=(
            "В кэше сейчас нет свежих матчей по вакансиям. "
            "Честный ответ: пусто. Предложи /today или «найди вакансии»."
        ),
        footer="Живой поиск — напиши «найди вакансии» или /today.",
    )


async def _talk_digest(
    session: AsyncSession, profile: Profile, *, live: bool
) -> str:
    items = await digest_service.build_digest(
        session,
        profile,
        scope="talks",
        do_ingest=live,
        include_talks=True,
        limit=5 if live else 3,
    )
    if live:
        return _fmt_items(
            items,
            header="Живой поиск конференций (не масс-медиа/ТВ):",
            empty=(
                "Живой поиск конференций пуст. Не предлагай НТВ и утренние шоу. "
                "Можно /talks позже."
            ),
            footer="СМИ и подкасты — /pitch по запросу.",
        )
    return _fmt_items(
        items,
        header="Снимок конференций из кэша (без ingest; не масс-медиа):",
        empty=(
            "В кэше нет конференций с датой подачи. "
            "Не предлагай масс-медиа и ТВ. Предложи «найди конференции» или /talks."
        ),
        footer="Живой поиск — «найди конференции» / /talks.",
    )


async def run_tools(
    session: AsyncSession,
    profile: Profile,
    tools: list[ToolName],
) -> str:
    """Выполнить tools и склеить текст для LLM-контекста."""
    if not tools:
        return ""
    parts: list[str] = []
    for name in tools:
        if name == "get_profile":
            parts.append("### Профиль\n" + _plain_profile(profile))
        elif name == "get_job_snapshot":
            parts.append("### Вакансии\n" + await _job_digest(session, profile, live=False))
        elif name == "refresh_jobs":
            parts.append("### Вакансии (live)\n" + await _job_digest(session, profile, live=True))
        elif name == "get_talk_snapshot":
            parts.append("### Выступления\n" + await _talk_digest(session, profile, live=False))
        elif name == "refresh_talks":
            parts.append(
                "### Выступления (live)\n" + await _talk_digest(session, profile, live=True)
            )
        elif name == "get_schedule":
            parts.append(
                "### Расписание\n" + schedule_service.format_schedule(profile.digest_schedule)
            )
    return "\n\n".join(parts)
