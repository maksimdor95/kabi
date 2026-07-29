"""Fallback-источник: любая пользовательская ссылка (личный сайт / ТГ / портфолио)."""

from __future__ import annotations

import httpx

from app.enrichment.signals import ProfileSignals
from app.enrichment.html_utils import html_to_text
from app.llm import client as llm
from app.observability.logging import get_logger

logger = get_logger("kabi.enrichment.generic")

_SYSTEM = (
    "Ты извлекаешь карьерные сигналы со страницы профиля/портфолио пользователя. "
    "Только факты со страницы. Ответ — строго JSON."
)

_PROMPT = """Из текста страницы извлеки JSON:
- speaking_topics: темы, на которые человек говорит/пишет (массив; [] если нет)
- extra_skills: навыки (массив; [] если нет)

Текст:
\"\"\"
{text}
\"\"\"
"""


class GenericSource:
    name = "generic"

    def matches(self, url: str) -> bool:
        return url.startswith("http://") or url.startswith("https://")

    async def fetch(self, url: str) -> ProfileSignals:
        text = await _fetch_page_text(url)
        if not text:
            return ProfileSignals(source_links=[url])
        data = await llm.complete_json(
            _PROMPT.format(text=text),
            system=_SYSTEM,
            tier="cheap",
        )
        if not isinstance(data, dict):
            return ProfileSignals(source_links=[url])
        return ProfileSignals(
            speaking_topics=list(data.get("speaking_topics") or []),
            extra_skills=list(data.get("extra_skills") or []),
            source_links=[url],
        )


async def _fetch_page_text(url: str) -> str:
    headers = {
        "User-Agent": "KabiCareerManager/0.1 (personal enrichment; user-provided link)",
        "Accept-Language": "ru-RU,ru;q=0.9",
    }
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers)
    if resp.status_code != 200:
        logger.warning("generic_fetch_failed status=%s url=%s", resp.status_code, url)
        return ""
    return html_to_text(resp.text)
