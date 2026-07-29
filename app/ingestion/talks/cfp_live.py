"""Live-парсер страниц CFP / «стать спикером».

Тянет HTML по cfp_url, через LLM извлекает дедлайн, даты события и статус
(open|closed|unknown). Используется для конференций из seed с полем cfp_url.

Спека: docs/services/ingestion.md (M3)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import httpx

from app.enrichment.html_utils import html_to_text
from app.llm import client as llm
from app.observability.logging import get_logger

logger = get_logger("kabi.ingestion.cfp")

_SYSTEM = (
    "Ты извлекаешь факты о Call for Papers / заявке спикера со страницы конференции. "
    "Только факты из текста. Ответ — строго JSON."
)

_PROMPT = """Из текста страницы CFP / «стать докладчиком» извлеки JSON:
- open: true если заявки СЕЙЧАС принимают, false если явно закрыты, null если неясно
- deadline: дата дедлайна заявки в формате YYYY-MM-DD или null
- event_start: дата начала события YYYY-MM-DD или null
- event_end: дата конца события YYYY-MM-DD или null
- note: короткая цитата/факт про статус (1 предложение) или ""

Сегодня ориентир: {today}. Если написано «принимали до 1 июня» — open=false, deadline=эта дата.

Текст:
\"\"\"
{text}
\"\"\"
"""


@dataclass
class CfpSnapshot:
    open: bool | None
    deadline: datetime | None
    event_start: datetime | None
    event_end: datetime | None
    note: str
    raw_ok: bool


def _parse_day(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        d = date.fromisoformat(value.strip()[:10])
        return datetime(d.year, d.month, d.day, 23, 59, tzinfo=timezone.utc)
    except ValueError:
        return None


async def fetch_cfp_page(url: str) -> CfpSnapshot:
    """Скачать страницу и извлечь CFP-метаданные."""
    headers = {
        "User-Agent": "KabiCareerManager/0.1 (personal; CFP monitor)",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    }
    try:
        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            logger.warning("cfp_fetch HTTP %s url=%s", resp.status_code, url)
            return CfpSnapshot(None, None, None, None, f"HTTP {resp.status_code}", False)
        text = html_to_text(resp.text)
    except httpx.HTTPError as exc:
        logger.warning("cfp_fetch error url=%s: %s", url, exc)
        return CfpSnapshot(None, None, None, None, str(exc), False)

    if not text or len(text) < 80:
        return CfpSnapshot(None, None, None, None, "пустая страница", False)

    try:
        data = await llm.complete_json(
            _PROMPT.format(
                text=text[:18000],
                today=date.today().isoformat(),
            ),
            system=_SYSTEM,
            tier="cheap",
        )
    except Exception as exc:
        logger.warning("cfp_llm failed url=%s: %s", url, exc)
        return CfpSnapshot(None, None, None, None, "LLM parse failed", False)

    if not isinstance(data, dict):
        return CfpSnapshot(None, None, None, None, "bad JSON", False)

    open_raw = data.get("open")
    open_flag: bool | None
    if open_raw is True:
        open_flag = True
    elif open_raw is False:
        open_flag = False
    else:
        open_flag = None

    return CfpSnapshot(
        open=open_flag,
        deadline=_parse_day(data.get("deadline")),
        event_start=_parse_day(data.get("event_start")),
        event_end=_parse_day(data.get("event_end")),
        note=str(data.get("note") or "")[:300],
        raw_ok=True,
    )
