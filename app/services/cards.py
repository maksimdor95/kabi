"""Поля карточки возможности, общие для бота и Mini App.

Здесь только presentation-neutral данные (строка зарплаты, «суть», «почему ты»,
подпись источника). Разметка — на стороне канала: HTML в `bot/keyboards`,
JSON в `app/api`. Спека: docs/services/digest.md, docs/services/miniapp.md.
"""

from __future__ import annotations

import re

from app.ingestion.normalize_job import clean_job_description, display_title, guess_org_from_title
from app.services.digest import DigestItem

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
# Служебный хвост ingestion (старые записи): «Темы: career_site, avito».
_TOPICS_TAIL_RE = re.compile(r"(?:\n|\s)*Темы\s*:\s*[^\n]*$", re.IGNORECASE)
# HH/snippet часто начинается с «...» или с середины предложения.
_LEADING_JUNK_RE = re.compile(r"^(?:\.{2,}|…|\s)+")

# Структурированный explain (см. matching.explain): СУТЬ + ПОЧЕМУ-буллеты.
_STRUCTURED_EXPLAIN_RE = re.compile(
    r"(?is)^\s*(?:СУТЬ|Суть)\s*:\s*(.+?)\s*(?:ПОЧЕМУ(?:\s*ТЫ)?|Почему(?:\s*ты)?)\s*:?\s*(.*)\s*$"
)
_WHY_ONLY_RE = re.compile(
    r"(?is)^\s*(?:ПОЧЕМУ(?:\s*ТЫ)?|Почему(?:\s*ты)?)\s*:?\s*(.*)\s*$"
)
_BULLET_LINE_RE = re.compile(r"^[\s]*[·•\-\*]\s*(.+)$")

# Fallback-суть из описания — короткая строка; structured essence не режем «…».
SNIPPET_LIMIT = 140
ESSENCE_LIMIT = 160
# С expandable-цитатой в Telegram можно держать полный «Почему ты».
REASON_LIMIT = 520
REASON_LIMIT_PITCH = 520


def format_salary(salary: dict | None) -> str | None:
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


def ellipsis_cut(text: str, *, limit: int) -> str:
    """Обрезать по границе слова и поставить …"""
    text = _WS_RE.sub(" ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0]
    return (cut or text[: limit - 1]).rstrip(".,;:…") + "…"


def snippet(text: str | None, *, limit: int = SNIPPET_LIMIT) -> str | None:
    """Короткая выжимка описания (fallback, если нет СУТЬ из explain)."""
    if not text:
        return None
    clean = _TOPICS_TAIL_RE.sub("", text)
    clean = _TAG_RE.sub(" ", clean)
    clean = _WS_RE.sub(" ", clean).strip()
    clean = _LEADING_JUNK_RE.sub("", clean).strip()
    if len(clean) < 40:
        return None
    if clean.lower().startswith("площадка:"):
        return None
    return ellipsis_cut(clean, limit=limit)


def reason_snippet(text: str | None, *, limit: int = REASON_LIMIT) -> str | None:
    """Прозаический «Почему ты» (старые Match без структуры)."""
    if not text:
        return None
    clean = _WS_RE.sub(" ", _TAG_RE.sub(" ", text)).strip()
    if len(clean) < 20:
        return None
    return ellipsis_cut(clean, limit=limit)


def _norm_bullets(block: str) -> str | None:
    """Нормализовать буллеты к «· …»; прозу оставить одной строкой."""
    raw = (block or "").strip()
    if not raw:
        return None
    lines: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _BULLET_LINE_RE.match(line)
        if m:
            body = m.group(1).strip().rstrip(".")
            if body:
                lines.append(f"· {body}")
        else:
            # LLM иногда пишет без маркеров — каждый непустой абзац = буллет
            body = line.rstrip(".")
            if body:
                lines.append(f"· {body}")
    if not lines:
        return None
    # не больше 3 буллетов на карточке
    return "\n".join(lines[:3])


def parse_explain(reason: str | None) -> tuple[str | None, str | None]:
    """Разобрать structured explain → (суть, почему_ты_буллеты).

    Формат из matching.explain:
        СУТЬ: ...
        ПОЧЕМУ:
        · ...
        · ...
    """
    if not reason or not reason.strip():
        return None, None
    text = reason.strip()
    m = _STRUCTURED_EXPLAIN_RE.match(text)
    if m:
        essence = _WS_RE.sub(" ", m.group(1)).strip().rstrip(".")
        why = _norm_bullets(m.group(2))
        if essence and len(essence) > ESSENCE_LIMIT:
            essence = ellipsis_cut(essence, limit=ESSENCE_LIMIT)
        return (essence or None), why
    m2 = _WHY_ONLY_RE.match(text)
    if m2 and ("\n" in text or _BULLET_LINE_RE.search(text)):
        return None, _norm_bullets(m2.group(1))
    # уже одни буллеты без заголовка
    if _BULLET_LINE_RE.search(text) and "\n" in text:
        return None, _norm_bullets(text)
    return None, None


def card_approach(item: DigestItem) -> str | None:
    """Блок «Как зайти» для talk/pitch (Pitch 2.0)."""
    if item.opp_type != "talk":
        return None
    if item.approach and len(item.approach.strip()) >= 20:
        return ellipsis_cut(item.approach.strip(), limit=520)
    raw = item.description or ""
    for line in raw.splitlines():
        low = line.strip().lower()
        if low.startswith("как зайти:"):
            body = line.split(":", 1)[-1].strip()
            if len(body) >= 20:
                return ellipsis_cut(body, limit=520)
    return None


def card_reason(item: DigestItem) -> str | None:
    """«Почему ты»: буллеты из structured explain или проза (legacy)."""
    _, why = parse_explain(item.reason)
    if why:
        return why
    limit = REASON_LIMIT_PITCH if item.opp_type == "talk" else REASON_LIMIT
    return reason_snippet(item.reason, limit=limit)


def card_title(item: DigestItem) -> tuple[str, str | None]:
    """Заголовок и работодатель после нормализации (для job — чистим мусор в title)."""
    org = item.org
    title = item.title
    if item.opp_type != "talk":
        org = org or guess_org_from_title(title, existing_org=org)
        title = display_title(title, org=org)
    return title, org


def card_summary(item: DigestItem, *, title: str | None = None) -> str | None:
    """«Суть» для job: сначала СУТЬ из explain, иначе короткий snippet описания."""
    if item.opp_type == "talk":
        return None
    essence, _ = parse_explain(item.reason)
    if essence and len(essence) >= 12:
        return essence
    raw = item.description
    headline = title or card_title(item)[0]
    raw = clean_job_description(raw, title=headline) or raw
    if not raw or len(raw.strip()) < 40:
        from_title = clean_job_description(item.title, title=headline)
        if from_title and len(from_title) >= 40:
            raw = from_title
    return snippet(raw)


_SOURCE_LABELS: dict[str, str] = {
    "hh.ru": "HeadHunter",
    "superjob.ru": "SuperJob",
    "career.habr.com": "Хабр Карьера",
    "getmatch.ru": "Getmatch",
    "geekjob.ru": "Geekjob",
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
    "open_cfp": "Конференции",
    "cfp_discovery": "Поиск конференций",
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
    """Человекочитаемый источник (на карточке не акцентируем)."""
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
