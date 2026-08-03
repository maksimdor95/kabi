"""Извлечение обновлений профиля из свободного чата (M9).

Только явные фразы — не трогаем онбординг-парсеры «вслепую» на любой текст.
Спека: docs/services/dialogue-agent.md
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.onboarding import parse_answer

_SALARY_HINT = re.compile(
    r"(зарплат|з\/?п\b|salary|ожидан\w*.{0,12}(от|мин)|минимум.{0,12}\d|"
    r"от\s+\d[\d\s]*\s*(тыс|тысяч|[кk]|руб|₽|\$))",
    re.I,
)
_HARD_NO_HINT = re.compile(
    r"(не предлагай|не хочу|не рассматрива|красный флаг|hard\s*no|"
    r"исключи|анти.?предпочт|не слать|не присылай)",
    re.I,
)
_PRIORITY_HINT = re.compile(
    r"(приоритет|фокус на|хочу только|дальше только|мне только|"
    r"переключи.{0,12}на)",
    re.I,
)
_LOCATION_HINT = re.compile(
    r"(?:живу в|переехал(?:а|и)? в|локация[:\s]+|город[:\s]+)\s*"
    r"([A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё\-\s]{1,40})",
    re.I,
)
_GOALS_HINT = re.compile(
    r"(?:моя цель[:\s]+|цель[:\s]+|хочу развивать(?:ся)?[:\s]*)(.+)",
    re.I,
)


@dataclass
class ChatProfileUpdate:
    patch: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def extract_chat_profile_update(text: str) -> ChatProfileUpdate:
    """Вернуть патч профиля, если пользователь явно просит обновить поля."""
    out = ChatProfileUpdate()
    t = (text or "").strip()
    if not t:
        return out

    if _SALARY_HINT.search(t):
        parsed = parse_answer("salary", t)
        if parsed.ok and parsed.patch:
            out.patch.update(parsed.patch)
            sal = parsed.patch.get("salary_expectation") or {}
            out.notes.append(
                f"зарплата от {sal.get('min')} {sal.get('currency') or 'RUB'}"
            )

    if _HARD_NO_HINT.search(t):
        parsed = parse_answer("hard_nos", t)
        if parsed.ok and parsed.patch is not None:
            out.patch.update(parsed.patch)
            raw = (parsed.patch.get("hard_nos") or {}).get("raw")
            if raw:
                out.notes.append(f"красные флаги: {raw[:120]}")
            else:
                out.notes.append("красные флаги очищены")

    if _PRIORITY_HINT.search(t):
        parsed = parse_answer("priorities", t)
        if parsed.ok and parsed.patch:
            out.patch.update(parsed.patch)
            prio = parsed.patch.get("priorities")
            label = {"job": "работа", "talk": "выступления", "both": "оба"}.get(
                prio, str(prio)
            )
            out.notes.append(f"приоритет → {label}")

    loc_m = _LOCATION_HINT.search(t)
    if loc_m:
        city = re.sub(r"\s+", " ", loc_m.group(1)).strip(" .,!;:")
        city = re.split(
            r"\s+(сейчас|уже|пока|теперь|работаю|удалённо|удаленно)\b",
            city,
            maxsplit=1,
            flags=re.I,
        )[0].strip()
        if len(city) >= 2:
            out.patch["location"] = city
            out.notes.append(f"локация → {city}")

    goals_m = _GOALS_HINT.search(t)
    if goals_m:
        goals = goals_m.group(1).strip(" .,!;:")
        if len(goals) >= 3:
            out.patch["goals"] = goals[:500]
            out.notes.append("цель обновлена")

    return out


def format_update_note(update: ChatProfileUpdate) -> str:
    if not update.notes:
        return ""
    return "Обновил в профиле: " + "; ".join(update.notes) + "."
