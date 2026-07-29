"""Источник обогащения: публичная страница резюме HH.

Спека: docs/services/enrichment.md
Для MVP берём публичный HTML по ссылке пользователя (не чужие резюме).
Официальный API резюме требует OAuth владельца — подключим позже.
"""

from __future__ import annotations

import re

import httpx

from app.enrichment.signals import ProfileSignals
from app.enrichment.html_utils import html_to_text
from app.llm import client as llm
from app.observability.logging import get_logger

logger = get_logger("kabi.enrichment.hh")

_HH_RE = re.compile(r"https?://(?:[\w.-]+\.)?hh\.ru/resume/", re.I)

_SYSTEM = (
    "Ты извлекаешь сигналы карьерного профиля из текста публичного резюме HH. "
    "Возвращай только факты из текста. Ответ — строго JSON."
)

_PROMPT = """Из текста публичного резюме извлеки JSON:
- speaking_topics: темы для выступлений (массив строк; [] если неясно)
- extra_skills: доп. навыки (массив строк)
- job_search_status: "active" | "passive" | "top_only" | null
  (active = активно ищет, passive = присматривается / не ищет, null если не указано)

Текст:
\"\"\"
{text}
\"\"\"
"""


class HHSource:
    name = "hh"

    def matches(self, url: str) -> bool:
        return bool(_HH_RE.search(url))

    async def fetch(self, url: str) -> ProfileSignals:
        text = await _fetch_page_text(url)
        if not text:
            logger.warning("hh_empty_page url=%s", url)
            return ProfileSignals(source_links=[url])
        data = await llm.complete_json(
            _PROMPT.format(text=text),
            system=_SYSTEM,
            tier="cheap",
        )
        if not isinstance(data, dict):
            return ProfileSignals(source_links=[url])
        status = data.get("job_search_status")
        if status not in {"active", "passive", "top_only", None}:
            status = None
        return ProfileSignals(
            speaking_topics=list(data.get("speaking_topics") or []),
            extra_skills=list(data.get("extra_skills") or []),
            job_search_status=status,
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
        logger.warning("hh_fetch_failed status=%s url=%s", resp.status_code, url)
        return ""
    return html_to_text(resp.text)
