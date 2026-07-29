"""Коннектор Getmatch (M7b).

Публичный веб-поиск — SPA + API за логином. Берём официальный публичный канал
https://t.me/s/g_jobchannel (ссылки getmatch.ru/vacancies/{id}) и при возможности
обогащаем карточку со страницы вакансии.

Спека: docs/services/ingestion.md
"""

from __future__ import annotations

import re
from html import unescape

import httpx

from app.ingestion.schemas import OpportunityDraft
from app.observability.logging import get_logger

logger = get_logger("kabi.ingestion.getmatch")

_UA = "KabiCareerManager/0.1 (personal; +https://t.me/YouUkabi_bot)"
_TG_URL = "https://t.me/s/g_jobchannel"
_VAC_RE = re.compile(
    r"https?://(?:www\.)?getmatch\.ru/vacancies/(\d+)",
    re.I,
)
_MSG_SPLIT = "tgme_widget_message_wrap"
_TEXT_RE = re.compile(
    r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
    re.S | re.I,
)
_TAG_RE = re.compile(r"<[^>]+>")
_TITLE_TAG_RE = re.compile(r"<title[^>]*>([^<]+)</title>", re.I)
_JSON_TITLE_RE = re.compile(r'"title"\s*:\s*"([^"\\]{5,160})"')


def _strip_html(raw: str) -> str:
    text = unescape(raw.replace("&nbsp;", " "))
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = _TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _relevant(text: str, needles: list[str]) -> bool:
    if not needles:
        return True
    low = text.lower()
    return any(n.lower() in low for n in needles if n)


def _title_from_message(text: str) -> str:
    """Первая содержательная строка; убрать декоративные префиксы."""
    text = text.strip()
    text = re.sub(r"^[🔶🔸▪️•\-\s]+", "", text)
    # часто: «Title, Company Локация: …»
    cut = re.split(r"\s+Локация\s*:", text, maxsplit=1, flags=re.I)[0]
    cut = re.split(r"\s+Отклик", cut, maxsplit=1, flags=re.I)[0]
    cut = cut.strip(" ·—-|")
    if len(cut) >= 8:
        return cut[:200]
    return text[:120] or "Вакансия Getmatch"


def _location_remote(text: str) -> tuple[str | None, bool]:
    remote = bool(re.search(r"#?Удаленк|#?Remote|удалённ|удаленн", text, re.I))
    locs = re.findall(r"#([A-Za-zА-Яа-яёЁ_]+)", text)
    nice = []
    for loc in locs:
        low = loc.lower()
        if low in {"удаленка", "remote", "hybrid", "гибрид"}:
            continue
        nice.append(loc.replace("_", " "))
    return (", ".join(nice[:4]) or None), remote


def parse_getmatch_channel(
    html: str,
    *,
    relevance: list[str],
    limit: int = 40,
) -> list[OpportunityDraft]:
    """Сообщения канала → черновики со ссылкой getmatch.ru/vacancies/{id}."""
    drafts: list[OpportunityDraft] = []
    seen: set[str] = set()
    for block in html.split(_MSG_SPLIT)[1:]:
        if len(drafts) >= limit:
            break
        ids = _VAC_RE.findall(block)
        if not ids:
            continue
        text_m = _TEXT_RE.search(block)
        text = _strip_html(text_m.group(1)) if text_m else _strip_html(block)
        if not _relevant(text, relevance):
            continue
        for vac_id in ids:
            if vac_id in seen:
                continue
            seen.add(vac_id)
            loc, remote = _location_remote(text)
            title = _title_from_message(text)
            drafts.append(
                OpportunityDraft(
                    type="job",
                    title=title,
                    org=None,
                    description=text[:2000],
                    location=loc,
                    remote=remote,
                    url=f"https://getmatch.ru/vacancies/{vac_id}",
                    source="getmatch.ru",
                    external_id=vac_id,
                    tags=["getmatch"],
                    meta={"kind": "getmatch_tg", "channel": "g_jobchannel"},
                )
            )
            if len(drafts) >= limit:
                break
    return drafts


def enrich_from_vacancy_html(html: str, draft: OpportunityDraft) -> OpportunityDraft:
    """Подтянуть title/org со страницы вакансии (best-effort)."""
    title = None
    m = _TITLE_TAG_RE.search(html)
    if m:
        raw = _strip_html(m.group(1))
        # «Вакансия X, работа в Y — getmatch»
        raw = re.sub(r"^Вакансия\s+", "", raw, flags=re.I)
        raw = re.split(r"\s+—\s+getmatch", raw, maxsplit=1, flags=re.I)[0]
        parts = re.split(r",\s*работа в\s+", raw, maxsplit=1, flags=re.I)
        title = parts[0].strip()[:200] if parts else raw[:200]
        if len(parts) > 1:
            org = re.split(r",\s*", parts[1], maxsplit=1)[0].strip()
            if org and not draft.org:
                draft.org = org[:120]
    if not title:
        jm = _JSON_TITLE_RE.search(html)
        if jm:
            title = jm.group(1)[:200]
    if title and (not draft.title or draft.title.startswith("🔶") or len(draft.title) > 120):
        draft.title = title
    return draft


class GetmatchConnector:
    source = "getmatch.ru"

    def __init__(self, *, enrich: bool = True, limit: int = 40) -> None:
        self.enrich = enrich
        self.limit = limit

    async def fetch(
        self, keywords: list[str], *, area: int | None = None
    ) -> list[OpportunityDraft]:
        del area
        relevance = [k for k in (keywords or []) if k]
        for extra in (
            "product",
            "продукт",
            "продакт",
            "cpo",
            "head of",
            "owner",
            "менеджер продукта",
            "руководитель продукт",
            "директор по продукту",
        ):
            if extra.lower() not in {r.lower() for r in relevance}:
                relevance.append(extra)

        async with httpx.AsyncClient(
            timeout=35.0,
            headers={"User-Agent": _UA, "Accept-Language": "ru,en;q=0.8"},
            follow_redirects=True,
        ) as client:
            try:
                resp = await client.get(_TG_URL)
            except Exception as exc:  # noqa: BLE001
                logger.warning("getmatch tg fetch failed: %s", exc)
                return []
            if resp.status_code != 200:
                logger.warning("getmatch tg → HTTP %s", resp.status_code)
                return []
            drafts = parse_getmatch_channel(
                resp.text, relevance=relevance, limit=self.limit
            )
            if self.enrich and drafts:
                # обогащаем первые N — не долбим сайт
                for d in drafts[:8]:
                    try:
                        page = await client.get(d.url or "")
                        if page.status_code == 200:
                            enrich_from_vacancy_html(page.text, d)
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("getmatch enrich %s: %s", d.external_id, exc)
            logger.info("getmatch: %d drafts", len(drafts))
            return drafts
