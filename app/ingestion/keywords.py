"""Вывод поисковых ключевых слов и региона из профиля пользователя.

Идея из Leo AI (scrapeProfileParams.ts): под каждого пользователя собираем
каталог по его ролям, а не по общему запросу. Для MVP берём роли напрямую —
они уже нормализованы CV-парсером (например «Head of Product», «CPO»).
"""

from __future__ import annotations

from app.db.models import Profile

# Справочник регионов HH (area). Москва=1, СПб=2.
_HH_AREA_BY_CITY: dict[str, int] = {
    "москва": 1,
    "moscow": 1,
    "санкт-петербург": 2,
    "спб": 2,
    "saint petersburg": 2,
    "st petersburg": 2,
}

_DEFAULT_HH_AREA = 1  # Москва по умолчанию


def derive_keywords(profile: Profile) -> list[str]:
    """Ключевые слова для поиска вакансий из ролей профиля."""
    seen: set[str] = set()
    keywords: list[str] = []
    for role in profile.roles or []:
        norm = role.strip()
        key = norm.lower()
        if norm and key not in seen:
            seen.add(key)
            keywords.append(norm)
    return keywords


def derive_hh_area(profile: Profile) -> int:
    """Регион HH из локации профиля (по умолчанию Москва)."""
    if not profile.location:
        return _DEFAULT_HH_AREA
    return _HH_AREA_BY_CITY.get(profile.location.strip().lower(), _DEFAULT_HH_AREA)
