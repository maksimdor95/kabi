"""Поля карточки возможности, общие для бота и Mini App.

Presentation-neutral данные (зарплата, суть, компания/продукт, почему ты,
подпись источника). Разметка — на стороне канала: HTML в `bot/keyboards`,
JSON в `app/api`. Спека: docs/services/sprint_b.md, digest.md, miniapp.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.ingestion.normalize_job import clean_job_description, display_title, guess_org_from_title
from app.services.digest import DigestItem

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_TOPICS_TAIL_RE = re.compile(r"(?:\n|\s)*Темы\s*:\s*[^\n]*$", re.IGNORECASE)
_LEADING_JUNK_RE = re.compile(r"^(?:\.{2,}|…|\s)+")

# Structured explain (Sprint B0): СУТЬ + опц. О_КОМПАНИИ/О_ПРОДУКТЕ + ПОЧЕМУ.
_FIELD_RE = re.compile(
    r"(?im)^\s*(СУТЬ|Суть|О_КОМПАНИИ|О компании|О_ПРОДУКТЕ|О продукте|"
    r"ПОЧЕМУ(?:\s*ТЫ)?|Почему(?:\s*ты)?)\s*:\s*(.*)$"
)
_BULLET_LINE_RE = re.compile(r"^[\s]*[·•\-\*]\s*(.+)$")
_META_BULLET_PREFIX_RE = re.compile(
    r"^(?:"
    r"(?:upside|anchor|disclaimer|risks?)\s*(?:\([^)]*\))?\s*[—–\-:]\s*"
    r"|(?:апсайд|якорь|оговорка|ход|мост|потолок|риск)\s*(?:\([^)]*\))?\s*[—–\-:]\s*"
    r")",
    re.IGNORECASE,
)
def _is_empty_signal(text: str) -> bool:
    t = text.strip().lower().rstrip(".")
    if t in {"—", "-", "–", "нет", "n/a", "na", "none", ""}:
        return True
    junk = (
        "нет информации о риск",
        "рисков нет",
        "риска нет",
        "оговорок нет",
        "оговорки нет",
        "нет оговор",
        "особенностей вакансии",
        "особенности вакансии",
    )
    return any(j in t for j in junk)

SNIPPET_LIMIT = 140
ESSENCE_LIMIT = 160
COMPANY_LIMIT = 160
PRODUCT_LIMIT = 160
DETAIL_LIMIT = 520
REASON_LIMIT = 520
REASON_LIMIT_PITCH = 520


@dataclass(frozen=True)
class ExplainParts:
    essence: str | None = None
    company: str | None = None
    product: str | None = None
    why: str | None = None


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
    text = _WS_RE.sub(" ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0]
    return (cut or text[: limit - 1]).rstrip(".,;:…") + "…"


def snippet(text: str | None, *, limit: int = SNIPPET_LIMIT) -> str | None:
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
    if not text:
        return None
    clean = _WS_RE.sub(" ", _TAG_RE.sub(" ", text)).strip()
    if len(clean) < 20:
        return None
    return ellipsis_cut(clean, limit=limit)


def _clean_fact(value: str | None, *, limit: int) -> str | None:
    if not value:
        return None
    text = _WS_RE.sub(" ", value).strip().strip("\"'«»")
    if not text or _is_empty_signal(text):
        return None
    return ellipsis_cut(text, limit=limit)


def _norm_bullets(block: str) -> str | None:
    raw = (block or "").strip()
    if not raw:
        return None
    lines: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _BULLET_LINE_RE.match(line)
        body = m.group(1).strip() if m else line
        body = _META_BULLET_PREFIX_RE.sub("", body).strip().rstrip(".")
        body = re.sub(
            r"^(?:upside|anchor|disclaimer|апсайд|якорь|оговорка)"
            r"(?:\s*\([^)]*\))?\s*[—–\-:]\s*",
            "",
            body,
            flags=re.I,
        ).strip()
        if not body or _is_empty_signal(body):
            continue
        lines.append(f"· {body}")
    if not lines:
        return None
    return "\n".join(lines[:3])


def parse_explain(reason: str | None) -> ExplainParts:
    """Разобрать structured explain → суть / компания / продукт / почему."""
    if not reason or not reason.strip():
        return ExplainParts()
    text = reason.strip()

    fields: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        m = _FIELD_RE.match(line)
        if m:
            label = m.group(1).lower().replace(" ", "_")
            if label.startswith("суть"):
                current = "essence"
            elif "компани" in label:
                current = "company"
            elif "продукт" in label:
                current = "product"
            elif label.startswith("почему"):
                current = "why"
            else:
                current = None
            rest = (m.group(2) or "").strip()
            fields.setdefault(current or "_", [])
            if current and rest:
                fields[current].append(rest)
            continue
        if current:
            fields.setdefault(current, []).append(line)

    if "essence" in fields or "why" in fields or "company" in fields:
        essence = _clean_fact(" ".join(fields.get("essence") or []), limit=ESSENCE_LIMIT)
        company = _clean_fact(" ".join(fields.get("company") or []), limit=COMPANY_LIMIT)
        product = _clean_fact(" ".join(fields.get("product") or []), limit=PRODUCT_LIMIT)
        why = _norm_bullets("\n".join(fields.get("why") or []))
        return ExplainParts(essence=essence, company=company, product=product, why=why)

    # legacy: СУТЬ:... ПОЧЕМУ:... одним блоком без доп. полей
    legacy = re.match(
        r"(?is)^\s*(?:СУТЬ|Суть)\s*:\s*(.+?)\s*(?:ПОЧЕМУ(?:\s*ТЫ)?|Почему(?:\s*ты)?)\s*:?\s*(.*)\s*$",
        text,
    )
    if legacy:
        return ExplainParts(
            essence=_clean_fact(legacy.group(1), limit=ESSENCE_LIMIT),
            why=_norm_bullets(legacy.group(2)),
        )
    if _BULLET_LINE_RE.search(text) and "\n" in text:
        return ExplainParts(why=_norm_bullets(text))
    return ExplainParts()


def card_approach(item: DigestItem) -> str | None:
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
    parts = parse_explain(item.reason)
    if parts.why:
        return parts.why
    limit = REASON_LIMIT_PITCH if item.opp_type == "talk" else REASON_LIMIT
    return reason_snippet(item.reason, limit=limit)


def card_company(item: DigestItem) -> str | None:
    if item.opp_type == "talk":
        return None
    return parse_explain(item.reason).company


def card_product(item: DigestItem) -> str | None:
    if item.opp_type == "talk":
        return None
    return parse_explain(item.reason).product


def card_title(item: DigestItem) -> tuple[str, str | None]:
    org = item.org
    title = item.title
    if item.opp_type != "talk":
        org = org or guess_org_from_title(title, existing_org=org)
        title = display_title(title, org=org)
    return title, org


def card_summary(item: DigestItem, *, title: str | None = None) -> str | None:
    if item.opp_type == "talk":
        return None
    essence = parse_explain(item.reason).essence
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


def card_detail(item: DigestItem, *, title: str | None = None) -> str | None:
    """Текст источника для expandable-цитаты (не дублирует Суть)."""
    if item.opp_type == "talk":
        return None
    headline = title or card_title(item)[0]
    raw = item.description
    raw = clean_job_description(raw, title=headline) or raw
    if not raw or len(raw.strip()) < 60:
        from_title = clean_job_description(item.title, title=headline)
        if from_title and len(from_title) >= 60:
            raw = from_title
    if not raw:
        return None
    clean = _TOPICS_TAIL_RE.sub("", raw)
    clean = _TAG_RE.sub(" ", clean)
    clean = _WS_RE.sub(" ", clean).strip()
    clean = _LEADING_JUNK_RE.sub("", clean).strip()
    if len(clean) < 60:
        return None
    essence = card_summary(item, title=headline)
    if essence and clean.lower().startswith(essence.lower()[:40]):
        rest = clean[len(essence) :].lstrip(" .,—–-")
        if len(rest) >= 60:
            clean = rest
        else:
            return None
    return ellipsis_cut(clean, limit=DETAIL_LIMIT)


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
