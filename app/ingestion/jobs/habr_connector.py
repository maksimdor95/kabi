"""Коннектор Хабр Карьера (M7d): публичный HTML-листинг + RSS.

Официальный API плохо стыкуется с proactive cache — HTML/RSS осознанный ToS-риск.
Спека: docs/services/ingestion.md
"""

from __future__ import annotations

import re
from html import unescape
from urllib.parse import quote_plus, urljoin
from xml.etree import ElementTree as ET

import httpx

from app.ingestion.schemas import OpportunityDraft
from app.observability.logging import get_logger

logger = get_logger("kabi.ingestion.habr")

_UA = "KabiCareerManager/0.1 (personal; +https://t.me/YouUkabi_bot)"
_BASE = "https://career.habr.com"
_RSS = f"{_BASE}/vacancies/rss"
_HTML = f"{_BASE}/vacancies"

_TITLE_WRAP_RE = re.compile(
    r"Требуется\s+[«\"](.+?)[»\"](?:\s*\((.*?)\))?",
    re.I | re.S,
)
_CARD_RE = re.compile(
    r'<div class="vacancy-card">'
    r'.*?<a aria-label="([^"]+)" class="vacancy-card__backdrop-link" '
    r'href="(/vacancies/\d+)"></a>'
    r"(.*?)"
    r'(?=<div class="vacancy-card">|$)',
    re.S | re.I,
)
_COMPANY_RE = re.compile(
    r'<a[^>]+href="/companies/[^"]+"[^>]*>([^<]+)</a>',
    re.I,
)
_SALARY_RE = re.compile(
    r'class="vacancy-card__salary[^"]*"[^>]*>(.*?)</(?:div|span)>',
    re.S | re.I,
)
_TAG_RE = re.compile(r"<[^>]+>")
_SALARY_NUM_RE = re.compile(
    r"(?:от\s+)?([\d\s\u00a0]+)\s*(?:до\s+([\d\s\u00a0]+))?\s*₽",
    re.I,
)


def _clean(text: str) -> str:
    text = unescape(_TAG_RE.sub(" ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def _relevant(text: str, needles: list[str]) -> bool:
    if not needles:
        return True
    low = text.lower()
    return any(n.lower() in low for n in needles if n)


def _parse_habr_title(raw: str) -> tuple[str, str | None]:
    """«Требуется «X» (Москва)» → (X, Москва)."""
    raw = _clean(raw)
    m = _TITLE_WRAP_RE.search(raw)
    if m:
        title = _clean(m.group(1))
        loc = _clean(m.group(2) or "") or None
        if loc and re.search(r"\d", loc) and "₽" in (loc or ""):
            # в скобках зарплата, не город
            loc = None
        return title or raw, loc
    return raw, None


def _parse_salary(blob: str) -> dict | None:
    m = _SALARY_NUM_RE.search(blob.replace("\xa0", " "))
    if not m:
        return None

    def _n(s: str | None) -> int | None:
        if not s:
            return None
        digits = re.sub(r"\D", "", s)
        return int(digits) if digits else None

    lo, hi = _n(m.group(1)), _n(m.group(2))
    if lo is None and hi is None:
        return None
    return {"min": lo, "max": hi, "currency": "RUB"}


def parse_habr_rss(xml_text: str, *, relevance: list[str]) -> list[OpportunityDraft]:
    drafts: list[OpportunityDraft] = []
    seen: set[str] = set()
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("habr rss parse error: %s", exc)
        return []

    for item in root.findall("./channel/item"):
        title_raw = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        guid = (item.findtext("guid") or "").strip()
        author = (item.findtext("author") or "").strip() or None
        desc = (item.findtext("description") or "").strip()
        if not title_raw or not link:
            continue
        title, loc_from_title = _parse_habr_title(title_raw)
        blob = f"{title} {author or ''} {desc}"
        if not _relevant(blob, relevance):
            continue
        ext = guid or link.rstrip("/").split("/")[-1]
        if ext in seen:
            continue
        seen.add(ext)
        remote = "удал" in desc.lower() or "remote" in desc.lower()
        drafts.append(
            OpportunityDraft(
                type="job",
                title=title[:200],
                org=author,
                description=_clean(desc)[:2000] or title,
                location=loc_from_title,
                remote=remote,
                salary=_parse_salary(title_raw + " " + desc),
                url=link,
                source="career.habr.com",
                external_id=str(ext),
                tags=["habr", "career"],
                meta={"kind": "habr_rss"},
            )
        )
    return drafts


def parse_habr_html(html: str, *, relevance: list[str]) -> list[OpportunityDraft]:
    drafts: list[OpportunityDraft] = []
    seen: set[str] = set()
    for title_raw, href, body in _CARD_RE.findall(html):
        title = _clean(unescape(title_raw))
        url = urljoin(_BASE, href)
        ext = href.rstrip("/").split("/")[-1]
        company_m = _COMPANY_RE.search(body)
        org = _clean(company_m.group(1)) if company_m else None
        salary_m = _SALARY_RE.search(body)
        salary_blob = _clean(salary_m.group(1)) if salary_m else ""
        blob = f"{title} {org or ''} {salary_blob} {_clean(body)[:400]}"
        if not _relevant(blob, relevance):
            continue
        if ext in seen:
            continue
        seen.add(ext)
        remote = "удал" in body.lower()
        drafts.append(
            OpportunityDraft(
                type="job",
                title=title[:200],
                org=org,
                description=title,
                remote=remote,
                salary=_parse_salary(salary_blob),
                url=url,
                source="career.habr.com",
                external_id=str(ext),
                tags=["habr", "career"],
                meta={"kind": "habr_html"},
            )
        )
    return drafts


class HabrCareerConnector:
    source = "career.habr.com"

    def __init__(self, *, per_keyword: int = 25) -> None:
        self.per_keyword = per_keyword

    async def fetch(
        self, keywords: list[str], *, area: int | None = None
    ) -> list[OpportunityDraft]:
        del area
        kws = [k for k in (keywords or []) if k][:5] or ["product"]
        relevance = list(kws)
        for extra in (
            "product",
            "продукт",
            "продакт",
            "cpo",
            "head of",
            "owner",
            "менеджер",
            "руководитель",
        ):
            if extra.lower() not in {r.lower() for r in relevance}:
                relevance.append(extra)

        out: list[OpportunityDraft] = []
        seen: set[str] = set()
        async with httpx.AsyncClient(
            timeout=35.0,
            headers={"User-Agent": _UA, "Accept-Language": "ru,en;q=0.8"},
            follow_redirects=True,
        ) as client:
            for kw in kws:
                q = quote_plus(kw)
                try:
                    rss_url = f"{_RSS}?page=1&per_page={self.per_keyword}&q={q}"
                    resp = await client.get(rss_url)
                    if resp.status_code == 200:
                        found = parse_habr_rss(resp.text, relevance=relevance)
                    else:
                        logger.warning("habr rss → HTTP %s", resp.status_code)
                        found = []
                    if len(found) < 3:
                        html_url = f"{_HTML}?q={q}&type=all"
                        href = await client.get(html_url)
                        if href.status_code == 200:
                            found = parse_habr_html(href.text, relevance=relevance)
                    for d in found:
                        if d.external_id in seen:
                            continue
                        seen.add(d.external_id or "")
                        out.append(d)
                    logger.info("habr q=%r: %d drafts", kw, len(found))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("habr q=%r failed: %s", kw, exc)
        return out
