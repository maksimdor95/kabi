"""Шаги онбординга, кнопки и парсеры с валидацией.

Спека: docs/services/dialogue-agent.md
Чистый модуль без БД/сети — легко тестируется.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

# Схема опциональна: «www.linkedin.com/in/…» тоже считаем ссылкой.
_URL_RE = re.compile(
    r"(?:https?://|(?<![@\w])www\.)[^\s<>\"']+",
    re.I,
)
URL_RE = _URL_RE  # публичный алиас для других модулей

# LinkedIn-страницы без профиля (лента, логин) — не enrichment-источник.
_JUNK_LINK_RE = re.compile(
    r"linkedin\.com/(?:feed|login|uas|checkpoint|authwall|signup|jobs)(?:/|$|\?)",
    re.I,
)

_NEG_EXACT = {"нет", "-", "no", "skip", "неважно", "пофиг", "пропустить"}
_NEG_PREFIXES = ("нет", "no ", "skip", "пропуст", "не важно", "не знаю", "без разницы")

_RESTART_PHRASES = ("начать заново", "сбросить онбординг", "заново онбординг", "reset onboarding")


def normalize_url(raw: str) -> str:
    """Почистить URL и добавить https:// при отсутствии схемы."""
    url = raw.rstrip(".,);]")
    if url.lower().startswith("www."):
        url = "https://" + url
    return url


def extract_urls(text: str) -> list[str]:
    """Извлечь и нормализовать URL из текста (с дедупом)."""
    seen: set[str] = set()
    out: list[str] = []
    for match in _URL_RE.findall(text or ""):
        url = normalize_url(match)
        key = url.lower()
        if key not in seen:
            seen.add(key)
            out.append(url)
    return out


def is_useful_profile_link(url: str) -> bool:
    """Отсечь LinkedIn /feed/ и прочий мусор без профиля."""
    return not bool(_JUNK_LINK_RE.search(url))


def filter_useful_links(urls: list[str]) -> tuple[list[str], list[str]]:
    """Разделить ссылки на полезные и отброшенные."""
    useful = [u for u in urls if is_useful_profile_link(u)]
    junk = [u for u in urls if not is_useful_profile_link(u)]
    return useful, junk


def is_restart_request(text: str) -> bool:
    t = (text or "").strip().lower()
    return any(p in t for p in _RESTART_PHRASES)


@dataclass(frozen=True)
class Step:
    key: str
    question: str
    buttons: tuple[str, ...] = ()
    hint: str = "Не понял ответ. Выбери вариант кнопкой или напиши понятнее."


STEPS: list[Step] = [
    Step(
        "consent_links",
        "Если есть что-то ещё — присылай (одним сообщением или несколькими):\n"
        "• LinkedIn (/in/…)\n"
        "• HH (публичное резюме)\n"
        "• личный сайт / портфолио (публикации, эфиры)\n"
        "• записи выступлений, подкасты, статьи\n\n"
        "Или нажми «Пропустить» — спрошу только самое нужное вручную.",
        buttons=("Пропустить",),
        hint="Пришли ссылки (сайт, LinkedIn /in/…, HH, выступления) или нажми «Пропустить».",
    ),
    Step(
        "priorities",
        "Что сейчас важнее — от этого зависит меню и что я мониторю сам:\n\n"
        "• Работа — только вакансии (кнопка «Вакансии»)\n"
        "• Выступления — СМИ/подкасты и конференции с дедлайном\n"
        "• Оба — и вакансии, и выступления (в меню будет всё)\n\n"
        "Выбери кнопку ниже. Потом можно сменить приоритет в /profile или написав в чат.",
        buttons=("Работа", "Выступления", "Оба"),
        hint="Выбери: Работа (вакансии), Выступления или Оба.",
    ),
    Step(
        "salary",
        "От какой суммы предложение по работе тебе интересно? Укажи минимум (можно кнопкой).\n"
        "Нужно, чтобы отсеять вакансии ниже этой вилки.",
        buttons=("от 300 000 ₽", "от 400 000 ₽", "от 500 000 ₽", "от 700 000 ₽"),
        hint="Нужна сумма, например «500 000» или «500к». Или выбери кнопку.",
    ),
    Step(
        "hard_nos",
        "Куда точно НЕ предлагать? (индустрии, тип продукта, размер компании).\n"
        "Это жёсткий фильтр в подборке — такие вакансии/площадки отбрасываю.",
        buttons=("Нет красных флагов",),
        hint="Напиши, чего избегать, или нажми «Нет красных флагов».",
    ),
]


@dataclass
class ParseResult:
    ok: bool
    patch: dict = field(default_factory=dict)


def _is_negative(text: str) -> bool:
    t = text.strip().lower()
    return t in _NEG_EXACT or any(t.startswith(w) for w in _NEG_PREFIXES)


def _parse_consent_links(text: str) -> ParseResult:
    links, _junk = filter_useful_links(extract_urls(text))
    t = text.strip().lower().replace("ё", "е")
    if links:
        # Новые ссылки на шаге согласия — заменяют старые (не мержим чужой LinkedIn).
        return ParseResult(
            ok=True,
            patch={"enrichment_consent": True, "source_links": {"links": links}},
        )
    # «Пропустить» / опечатки вроде «пропустит»
    if t in {"пропустить", "пропустит", "пропуская", "skip"} or "пропуст" in t:
        return ParseResult(
            ok=True,
            patch={"enrichment_consent": True, "source_links": {"links": []}},
        )
    if _is_negative(text):
        return ParseResult(
            ok=True,
            patch={"enrichment_consent": False, "source_links": {"links": []}},
        )
    if t in {"ок", "окей", "да", "хорошо", "можно", "согласен", "согласна"}:
        return ParseResult(ok=True, patch={"enrichment_consent": True})
    return ParseResult(ok=False)


def _parse_priorities(text: str) -> ParseResult:
    t = text.lower().strip().replace("ё", "е")
    # Короткие ответы / первая буква кнопок
    if t in {"оба", "both", "о", "2"}:
        return ParseResult(ok=True, patch={"priorities": "both"})
    if t in {"работа", "вакансии", "job", "р", "1"}:
        return ParseResult(ok=True, patch={"priorities": "job"})
    if t in {"выступления", "выступление", "talks", "talk", "в", "3"}:
        return ParseResult(ok=True, patch={"priorities": "talk"})
    if "работ" in t and ("выступ" in t or "спик" in t or "конфер" in t):
        return ParseResult(ok=True, patch={"priorities": "both"})
    if any(w in t for w in ("работ", "ваканс", "job")) and not any(
        w in t for w in ("выступ", "спик", "конфер", "talk")
    ):
        return ParseResult(ok=True, patch={"priorities": "job"})
    if any(w in t for w in ("выступ", "спик", "конфер", "talk", "доклад")) and not any(
        w in t for w in ("работ", "ваканс", "job")
    ):
        return ParseResult(ok=True, patch={"priorities": "talk"})
    return ParseResult(ok=False)


def _parse_salary(text: str) -> ParseResult:
    t = text.lower().replace("\u00a0", " ")
    currency = "RUB"
    if "$" in t or "usd" in t or "долл" in t:
        currency = "USD"
    elif "€" in t or "eur" in t or "евро" in t:
        currency = "EUR"

    k_match = re.search(r"(\d+)\s*[кk]\b", t)
    if k_match:
        return ParseResult(
            ok=True,
            patch={"salary_expectation": {"min": int(k_match.group(1)) * 1000, "currency": currency}},
        )

    digits = re.findall(r"\d[\d \.]*", t)
    numbers = [int(re.sub(r"[ \.]", "", d)) for d in digits if re.sub(r"[ \.]", "", d)]
    numbers = [n for n in numbers if n >= 1000]
    if not numbers:
        return ParseResult(ok=False)
    return ParseResult(
        ok=True,
        patch={"salary_expectation": {"min": min(numbers), "currency": currency}},
    )


def _parse_status(text: str) -> ParseResult:
    t = text.lower().strip()
    if "актив" in t:
        return ParseResult(ok=True, patch={"job_search_status": "active"})
    if "топ" in t or "только луч" in t or t == "top":
        return ParseResult(ok=True, patch={"job_search_status": "top_only"})
    if "присматри" in t or "пассив" in t or "смотря" in t:
        return ParseResult(ok=True, patch={"job_search_status": "passive"})
    return ParseResult(ok=False)


def _parse_hard_nos(text: str) -> ParseResult:
    t = text.strip().lower()
    if _is_negative(text) or "нет красных" in t or t in {"нет флагов", "нет"}:
        return ParseResult(ok=True, patch={"hard_nos": {}})
    if not text.strip():
        return ParseResult(ok=False)
    return ParseResult(ok=True, patch={"hard_nos": {"raw": text.strip()}})


def _parse_availability(text: str) -> ParseResult:
    t = text.strip().lower()
    if not t:
        return ParseResult(ok=False)

    busy: bool | None = None
    if any(w in t for w in ("свобод", "сразу", "готов", "сейчас могу", "дома", "не работ")):
        busy = False
    if any(w in t for w in ("занят", "работаю", "на работе", "трудоустроен")):
        busy = True

    weeks: int | None = None
    if "сразу" in t or ("сейчас" in t and "недел" not in t):
        weeks = 0
    m = re.search(r"(\d+)\s*\+?\s*нед", t)
    if m:
        weeks = int(m.group(1))
    elif "8+" in t or "восемь" in t:
        weeks = 8

    if "свобод" in t and ("сразу" in t or weeks == 0):
        return ParseResult(
            ok=True,
            patch={"availability": {"busy": False, "weeks": 0, "raw": text.strip()}},
        )
    if busy is True and weeks is not None:
        return ParseResult(
            ok=True,
            patch={"availability": {"busy": True, "weeks": weeks, "raw": text.strip()}},
        )
    if busy is False and weeks is not None:
        return ParseResult(
            ok=True,
            patch={"availability": {"busy": False, "weeks": weeks, "raw": text.strip()}},
        )
    if weeks is not None and weeks > 0:
        return ParseResult(
            ok=True,
            patch={"availability": {"busy": True, "weeks": weeks, "raw": text.strip()}},
        )
    # Мягкий фолбэк: поняли «не на работе» без срока → свободен, выход ASAP
    if busy is False:
        return ParseResult(
            ok=True,
            patch={"availability": {"busy": False, "weeks": 0, "raw": text.strip()}},
        )
    return ParseResult(ok=False)


_PARSERS: dict[str, Callable[[str], ParseResult]] = {
    "consent_links": _parse_consent_links,
    "priorities": _parse_priorities,
    "salary": _parse_salary,
    "status": _parse_status,
    "hard_nos": _parse_hard_nos,
    "availability": _parse_availability,
}


def parse_answer(step_key: str, text: str) -> ParseResult:
    """Разобрать ответ. ok=False → нужно переспросить."""
    parser = _PARSERS.get(step_key)
    if parser is None:
        return ParseResult(ok=False)
    return parser(text)


def interpret_answer(step_key: str, text: str) -> dict:
    """Совместимость: патч или {} если не разобрали."""
    result = parse_answer(step_key, text)
    return result.patch if result.ok else {}


def step_by_index(idx: int) -> Step | None:
    if 0 <= idx < len(STEPS):
        return STEPS[idx]
    return None
