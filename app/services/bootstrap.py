"""Быстрый сид профиля без PDF (Sprint A).

Спека: docs/services/sprint_a.md
"""

from __future__ import annotations

from app.domain.profile import ProfileDraft
from app.llm import client as llm
from app.observability.logging import get_logger

logger = get_logger("kabi.bootstrap")

_SYSTEM = (
    "Из текста кандидата извлеки JSON-профиль. Только факты из текста, ничего не выдумывай.\n"
    "Схема: {\n"
    '  "roles": ["строка"],\n'
    '  "skills": ["строка"],\n'
    '  "location": "город или null",\n'
    '  "work_mode": "remote|hybrid|office|null",\n'
    '  "goals": "куда целится или null",\n'
    '  "salary_expectation": {"min": число, "currency": "RUB"} или null\n'
    "}\n"
    "Если ролей нет — угадай 1 из контекста осторожно. skills — ключевые слова."
)


async def draft_from_text(text: str) -> ProfileDraft:
    """Структурировать свободный текст в ProfileDraft через LLM."""
    data = await llm.complete_json(
        f"Текст кандидата:\n{text.strip()[:4000]}",
        system=_SYSTEM,
        tier="cheap",
    )
    if not isinstance(data, dict):
        data = {}
    roles = [str(x).strip() for x in (data.get("roles") or []) if str(x).strip()]
    skills = [str(x).strip() for x in (data.get("skills") or []) if str(x).strip()]
    if not roles:
        # эвристика: первая строка / куски до запятой
        guess = text.strip().split("\n")[0][:120]
        roles = [guess] if len(guess) >= 3 else ["Product Manager"]
    sal = data.get("salary_expectation")
    if not isinstance(sal, dict) or not sal.get("min"):
        sal = None
    location = data.get("location") or "не указано"
    work_mode = data.get("work_mode") or "remote"
    if work_mode not in {"remote", "hybrid", "office"}:
        work_mode = "remote"
    return ProfileDraft(
        roles=roles[:8],
        skills=skills[:40],
        location=str(location)[:80],
        work_mode=work_mode,
        goals=(str(data["goals"])[:500] if data.get("goals") else None),
        salary_expectation=sal,
    )


def text_looks_like_profile_seed(text: str) -> bool:
    """Достаточно ли текста, чтобы пробовать сид без PDF."""
    t = (text or "").strip()
    if len(t) < 12:
        return False
    low = t.lower()
    # выбор пункта меню / приветствие — не сид
    if low in {
        "1",
        "2",
        "3",
        "текст",
        "text",
        "pdf",
        "docx",
        "резюме",
        "ссылка",
        "привет",
        "hello",
        "hi",
        "start",
    }:
        return False
    hints = (
        "product",
        "продукт",
        "продакт",
        "менеджер",
        "оунер",
        "owner",
        "pm",
        "cpo",
        "роль",
        "ищу",
        "опыт",
        "лет",
        "senior",
        "middle",
        "junior",
        "lead",
        "head",
        "ваканс",
        "аналит",
        "разработ",
        "engineer",
        "директор",
        "сбер",
        "яндекс",
        "авито",
        "тиньк",
        "hh.ru",
        "linkedin",
    )
    return any(h in low for h in hints) or len(t) >= 40
