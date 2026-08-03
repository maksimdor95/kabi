"""Инструменты советника (M9): чтение профиля / снимка подборки / расписания.

Спека: docs/services/dialogue-agent.md
Детерминированный роутер интентов — без native function calling.
Digest вызывается с do_ingest=False (не трогаем воронку из чата).
"""

from __future__ import annotations

import re
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Profile
from app.services import digest as digest_service
from app.services import profile as profile_service
from app.services import schedule as schedule_service

ToolName = Literal["get_profile", "get_job_snapshot", "get_talk_snapshot", "get_schedule"]

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
    """Выбрать tools по тексту пользователя (порядок стабильный, без дублей)."""
    found: list[ToolName] = []
    for name, pat in _TOOL_PATTERNS:
        if pat.search(text) and name not in found:
            found.append(name)
    return found


def _plain_profile(profile: Profile) -> str:
    card = profile_service.format_profile_card(profile)
    return re.sub(r"</?b>", "", card)


async def _job_snapshot(session: AsyncSession, profile: Profile) -> str:
    items = await digest_service.build_digest(
        session,
        profile,
        scope="jobs",
        do_ingest=False,
        limit=3,
    )
    if not items:
        return (
            "В кэше сейчас нет свежих матчей по вакансиям. "
            "Честный ответ: пусто. Предложи пользователю /today для живого поиска."
        )
    lines = ["Снимок вакансий из кэша (без нового ingest):"]
    for i, it in enumerate(items, 1):
        org = f" · {it.org}" if it.org else ""
        reason = f" — {it.reason}" if it.reason else ""
        lines.append(f"{i}. {it.title}{org}{reason}")
        if it.url:
            lines.append(f"   {it.url}")
    lines.append("Полная подборка с обновлением источников — /today.")
    return "\n".join(lines)


async def _talk_snapshot(session: AsyncSession, profile: Profile) -> str:
    # Не смешиваем pitch (СМИ/ТВ evergreen) с CFP: для чата — talks с датой.
    items = await digest_service.build_digest(
        session,
        profile,
        scope="talks",
        do_ingest=False,
        include_talks=True,
        limit=3,
    )
    if not items:
        return (
            "В кэше нет конференций/CFP с датой. "
            "Не предлагай масс-медиа и ТВ. Предложи /talks или /pitch по запросу."
        )
    lines = ["Снимок CFP/конференций из кэша (без ingest; не масс-медиа):"]
    for i, it in enumerate(items, 1):
        org = f" · {it.org}" if it.org else ""
        dl = f", дедлайн {it.deadline.date().isoformat()}" if it.deadline else ""
        reason = f" — {it.reason}" if it.reason else ""
        lines.append(f"{i}. {it.title}{org}{dl}{reason}")
        if it.url:
            lines.append(f"   {it.url}")
    lines.append("Живой поиск — /talks. Питч в СМИ/подкасты — /pitch (по запросу).")
    return "\n".join(lines)


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
            parts.append("### Вакансии\n" + await _job_snapshot(session, profile))
        elif name == "get_talk_snapshot":
            parts.append("### Выступления\n" + await _talk_snapshot(session, profile))
        elif name == "get_schedule":
            parts.append(
                "### Расписание\n" + schedule_service.format_schedule(profile.digest_schedule)
            )
    return "\n\n".join(parts)
