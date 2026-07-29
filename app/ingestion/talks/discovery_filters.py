"""Фильтры discovery CFP: регион (карта) + ниша.

Спека: docs/services/ingestion.md (M6)
"""

from __future__ import annotations

import re

# Регион «подходит» для RU product-менеджера: online или РФ/ближайшее.
_REGION_ALLOW = (
    "online",
    "remote",
    "virtual",
    "hybrid",
    "russia",
    "russian",
    "москва",
    "moscow",
    "спб",
    "питер",
    "петербург",
    "saint petersburg",
    "st. petersburg",
    "санкт",
    "казань",
    "екатеринбург",
    "новосибирск",
    "минск",
    "киев",
    "tbilisi",
    "тбилиси",
    "yerevan",
    "ереван",
    "алматы",
    "almaty",
    "europe",
    "eu ",
    " ес",
)

# Явно «далеко и офлайн» без online в строке — режем (US/LATAM/… meetup).
_REGION_BLOCK_OFFLINE = (
    "united states",
    " usa",
    "u.s.",
    " california",
    " new york",
    " texas",
    " colorado",
    " missouri",
    " kenya",
    " nairobi",
    " indonesia",
    " jakarta",
    " costa rica",
    " medellin",
    " medellín",
    " canada",
    " saskatoon",
)

# Ниши по умолчанию (product / growth / AI / HR-tech).
DEFAULT_NICHE_KEYWORDS = (
    "product",
    "продукт",
    "cpo",
    "product owner",
    "product management",
    "growth",
    "management",
    "менеджмент",
    "leadership",
    "лидер",
    "ai",
    "агент",
    "agent",
    "hr",
    "people",
    "edtech",
    "обучен",
    "career",
    "карьер",
    "analytics",
    "аналитик",
    "devops",  # соседние tech-сцены, часто полезны PO
    "engineering",
    "разработ",
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def matches_region(location: str, *, title: str = "") -> bool:
    """True если локация ок для RU/online профиля."""
    blob = _norm(f"{location} {title}")
    if not blob:
        return True
    has_online = any(k in blob for k in ("online", "remote", "virtual", "hybrid"))
    if has_online:
        return True
    if any(k in blob for k in _REGION_ALLOW):
        return True
    if any(k in blob for k in _REGION_BLOCK_OFFLINE):
        return False
    # Неизвестная офлайн-локация — пока пропускаем (накапливаем осторожно).
    return False


def matches_niche(text: str, keywords: tuple[str, ...] | list[str] | None = None) -> bool:
    """True если заголовок/теги пересекаются с нишей."""
    blob = _norm(text)
    if not blob:
        return False
    keys = tuple(keywords) if keywords else DEFAULT_NICHE_KEYWORDS
    return any(_norm(k) in blob for k in keys if k)


def profile_niche_keywords(
    speaking_topics: list[str] | None = None,
    roles: list[str] | None = None,
    skills: list[str] | None = None,
) -> list[str]:
    """Ключевые слова ниши: дефолт + сигналы профиля."""
    extra: list[str] = []
    for part in (speaking_topics or []) + (roles or []) + (skills or []):
        t = (part or "").strip()
        if len(t) >= 3:
            extra.append(t)
    # дефолт первыми — стабильный recall
    seen: set[str] = set()
    out: list[str] = []
    for k in list(DEFAULT_NICHE_KEYWORDS) + extra:
        low = k.lower()
        if low not in seen:
            seen.add(low)
            out.append(k)
    return out
