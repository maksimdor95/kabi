"""M6: discovery открытых CFP с PaperCall.io (публичный каталог).

Сигнал → фильтр регион/ниша → парсинг дедлайна со страницы события.
Без API-ключа. Yaml не нужен — пользователь ничего не вводит.

Спека: docs/services/ingestion.md (M6)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import httpx

from app.enrichment.html_utils import html_to_text
from app.ingestion.talks.discovery_filters import matches_niche, matches_region
from app.ingestion.talks.url_quality import is_actionable_cfp_url
from app.observability.logging import get_logger

logger = get_logger("kabi.ingestion.papercall")

_LIST_URL = "https://www.papercall.io/cfps"
_UA = "KabiCareerManager/0.1 (personal; CFP discovery)"

_EVENT_HREF_RE = re.compile(
    r'href="(https://www\.papercall\.io/([a-z0-9-]+))"[^>]*>(.*?)</a>',
    re.I | re.S,
)
_SKIP_SLUGS = frozenset(
    {
        "assets",
        "events",
        "past_events",
        "pricing",
        "signin",
        "speakerpro",
        "auth",
        "help",
        "cfps",
    }
)
_CLOSE_RE = re.compile(
    r"CFP closes at\s+([A-Za-z]+ \d{1,2}, \d{4})",
    re.I,
)
_EVENT_DATE_RE = re.compile(
    r"\b([A-Za-z]+ \d{1,2}, \d{4})\b",
)
_TAGS_RE = re.compile(r"Tags:\s*(.+?)(?:CFP closes|CFP Description|$)", re.I | re.S)


@dataclass(frozen=True)
class PapercallListing:
    slug: str
    name: str
    location: str
    cfp_url: str


@dataclass
class PapercallEvent:
    slug: str
    name: str
    location: str
    cfp_url: str
    deadline: datetime | None
    event_start: datetime | None
    topics: list[str]
    open: bool | None


def _strip_html(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = (
        text.replace("&amp;", "&")
        .replace("&nbsp;", " ")
        .replace("&#39;", "'")
        .replace("&quot;", '"')
    )
    return re.sub(r"\s+", " ", text).strip()


def _parse_english_date(raw: str) -> datetime | None:
    text = (raw or "").strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            d = datetime.strptime(text, fmt)
            return d.replace(hour=23, minute=59, tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def parse_listing_html(html: str) -> list[PapercallListing]:
    """Из HTML /cfps достать уникальные события (slug + название + локация)."""
    found: dict[str, PapercallListing] = {}
    for m in _EVENT_HREF_RE.finditer(html or ""):
        url, slug, inner = m.group(1), m.group(2), _strip_html(m.group(3))
        if slug in _SKIP_SLUGS or not inner or inner.lower() == "submit now!":
            continue
        # «Name - Location» или «Name — Location»
        name, loc = inner, ""
        for sep in (" - ", " — ", " – "):
            if sep in inner:
                name, loc = inner.rsplit(sep, 1)
                name, loc = name.strip(), loc.strip()
                break
        if slug not in found or len(name) > len(found[slug].name):
            found[slug] = PapercallListing(
                slug=slug,
                name=name or slug,
                location=loc,
                cfp_url=url.split("?")[0],
            )
    return list(found.values())


def parse_event_html(html: str, listing: PapercallListing) -> PapercallEvent:
    text = html_to_text(html, max_chars=20000)
    deadline = None
    m = _CLOSE_RE.search(text)
    if m:
        deadline = _parse_english_date(m.group(1))

    event_start = None
    # После названия часто «Online September 24, 2026»
    dates = _EVENT_DATE_RE.findall(text[:800])
    for raw in dates:
        dt = _parse_english_date(raw)
        if dt and (deadline is None or dt.date() != deadline.date()):
            event_start = dt.replace(hour=0, minute=0)
            break

    topics: list[str] = []
    tm = _TAGS_RE.search(text)
    if tm:
        topics = [
            t.strip(" ,.")
            for t in re.split(r"[,/]", tm.group(1))
            if t.strip(" ,.") and len(t.strip()) < 40
        ][:12]

    open_flag: bool | None = None
    if deadline is not None:
        open_flag = deadline >= datetime.now(timezone.utc)
    elif "cfp is open" in text.lower() or "submit a talk" in text.lower():
        open_flag = True

    return PapercallEvent(
        slug=listing.slug,
        name=listing.name,
        location=listing.location or ("online" if "online" in text.lower()[:400] else ""),
        cfp_url=listing.cfp_url,
        deadline=deadline,
        event_start=event_start,
        topics=topics,
        open=open_flag,
    )


def filter_listings(
    listings: Iterable[PapercallListing],
    *,
    niche_keywords: list[str] | None = None,
) -> list[PapercallListing]:
    out: list[PapercallListing] = []
    for item in listings:
        blob = f"{item.name} {item.location} {item.slug}"
        if not matches_region(item.location, title=item.name):
            continue
        if not matches_niche(blob, niche_keywords):
            continue
        if not is_actionable_cfp_url(item.cfp_url):
            continue
        out.append(item)
    return out


async def fetch_open_cfps(
    *,
    niche_keywords: list[str] | None = None,
    limit: int = 20,
    client: httpx.AsyncClient | None = None,
) -> list[PapercallEvent]:
    """Каталог PaperCall → фильтр → детали события."""
    headers = {"User-Agent": _UA, "Accept-Language": "en,ru;q=0.8"}
    own = client is None
    http = client or httpx.AsyncClient(timeout=25, follow_redirects=True, headers=headers)
    try:
        resp = await http.get(_LIST_URL)
        if resp.status_code != 200:
            logger.warning("papercall list HTTP %s", resp.status_code)
            return []
        listings = filter_listings(parse_listing_html(resp.text), niche_keywords=niche_keywords)
        logger.info("papercall listing matched=%d", len(listings))
        events: list[PapercallEvent] = []
        for item in listings[:limit]:
            try:
                er = await http.get(item.cfp_url)
                if er.status_code != 200:
                    continue
                ev = parse_event_html(er.text, item)
                if ev.open is False:
                    continue
                events.append(ev)
            except httpx.HTTPError as exc:
                logger.warning("papercall event %s: %s", item.slug, exc)
        return events
    finally:
        if own:
            await http.aclose()
