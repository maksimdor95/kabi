"""Коннектор Geekjob.ru (M7e).

Публичный листинг /vacancies (+ пагинация), карточки li.collection-item.
Детали (опционально) — schema.org JobPosting JSON-LD на /vacancy/{hex}.

Спека: docs/services/ingestion.md
"""

from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import urljoin

import httpx

from app.ingestion.schemas import OpportunityDraft
from app.observability.logging import get_logger

logger = get_logger("kabi.ingestion.geekjob")

_UA = "KabiCareerManager/0.1 (personal; +https://t.me/YouUkabi_bot)"
_BASE = "https://geekjob.ru"
_LIST = f"{_BASE}/vacancies"
_ITEM_RE = re.compile(
    r'<li[^>]*class="[^"]*collection-item[^"]*"[^>]*>(.*?)</li>',
    re.S | re.I,
)
_HREF_VAC_RE = re.compile(r'href="(/vacancy/([a-f0-9]{16,32}))"', re.I)
_TITLE_RE = re.compile(r'class="title"[^>]*>(.*?)</a>', re.S | re.I)
_COMPANY_RE = re.compile(
    r'company-name"[^>]*>.*?<a[^>]*>(.*?)</a>',
    re.S | re.I,
)
_TAG_RE = re.compile(r"<[^>]+>")
_LD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.S | re.I,
)
_MAX_PAGES = 5
_MAX_DRAFTS = 40


def _clean(text: str) -> str:
    text = unescape(_TAG_RE.sub(" ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


_PRODUCT_CORE_RE = re.compile(
    r"(?:"
    r"\bproduct\b|продукт|продакт|produkt|\bcpo\b|"
    r"product\s+manager|product\s+owner|product\s+lead|"
    r"head\s+of\s+product|директор\s+по\s+продукт|"
    r"руководитель\s+продукт|менеджер\s+продукт|"
    r"владелец\s+продукт"
    r")",
    re.I,
)


def _relevant(text: str, needles: list[str]) -> bool:
    """Для Geekjob — только явный product-сигнал (не любой manager/lead)."""
    del needles  # профиль расширяет список, но ядро — product-трек
    return bool(_PRODUCT_CORE_RE.search(text or ""))


def parse_geekjob_listing(
    html: str,
    *,
    relevance: list[str],
    limit: int = _MAX_DRAFTS,
) -> list[OpportunityDraft]:
    drafts: list[OpportunityDraft] = []
    seen: set[str] = set()
    for block in _ITEM_RE.findall(html):
        if len(drafts) >= limit:
            break
        hm = _HREF_VAC_RE.search(block)
        tm = _TITLE_RE.search(block)
        if not hm or not tm:
            continue
        vac_id = hm.group(2).lower()
        if vac_id in seen:
            continue
        title = _clean(tm.group(1))
        if len(title) < 4:
            continue
        if not _relevant(title, relevance):
            continue
        seen.add(vac_id)
        cm = _COMPANY_RE.search(block)
        org = _clean(cm.group(1)) if cm else None
        remote = bool(re.search(r"remote-label|>\s*remote\s*<", block, re.I))
        url = urljoin(_BASE, hm.group(1))
        drafts.append(
            OpportunityDraft(
                type="job",
                title=title[:200],
                org=org,
                description=title,
                location=None,
                remote=remote,
                url=url,
                source="geekjob.ru",
                external_id=vac_id,
                tags=["geekjob"],
                meta={"kind": "geekjob_listing"},
            )
        )
    return drafts


def enrich_from_jsonld(html: str, draft: OpportunityDraft) -> OpportunityDraft:
    """Подтянуть описание/локацию/ЗП из JobPosting JSON-LD (best-effort)."""
    m = _LD_RE.search(html)
    if not m:
        return draft
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return draft
    if isinstance(data, list):
        data = next((x for x in data if isinstance(x, dict)), None)
    if not isinstance(data, dict):
        return draft
    if data.get("@type") not in ("JobPosting", ["JobPosting"]):
        types = data.get("@type")
        if types != "JobPosting" and (
            not isinstance(types, list) or "JobPosting" not in types
        ):
            return draft
    title = str(data.get("title") or "").strip()
    if title:
        draft.title = title[:200]
    desc = str(data.get("description") or "").strip()
    if desc:
        draft.description = _clean(desc)[:2500]
    org = data.get("hiringOrganization")
    if isinstance(org, dict) and org.get("name"):
        draft.org = str(org["name"])[:120]
    loc = data.get("jobLocation")
    if isinstance(loc, dict):
        addr = loc.get("address")
        if isinstance(addr, dict):
            bits = [
                addr.get("addressLocality"),
                addr.get("addressRegion"),
                addr.get("addressCountry"),
            ]
            place = ", ".join(str(b) for b in bits if b)
            if place:
                draft.location = place[:160]
    return draft


class GeekjobConnector:
    source = "geekjob.ru"

    def __init__(self, *, enrich: bool = True, max_pages: int = _MAX_PAGES) -> None:
        self.enrich = enrich
        self.max_pages = max_pages

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
            "product manager",
            "product owner",
            "директор по продукту",
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
            for page in range(1, self.max_pages + 1):
                url = _LIST if page == 1 else f"{_LIST}?page={page}"
                try:
                    resp = await client.get(url)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("geekjob page %s failed: %s", page, exc)
                    break
                if resp.status_code != 200:
                    logger.warning("geekjob page %s → HTTP %s", page, resp.status_code)
                    break
                found = parse_geekjob_listing(
                    resp.text, relevance=relevance, limit=_MAX_DRAFTS
                )
                if not found and page > 1:
                    # страница без product — всё равно листаем дальше? стоп если пусто полностью
                    raw_n = len(_ITEM_RE.findall(resp.text))
                    if raw_n == 0:
                        break
                for d in found:
                    if d.external_id in seen:
                        continue
                    seen.add(str(d.external_id))
                    out.append(d)
                    if len(out) >= _MAX_DRAFTS:
                        break
                if len(out) >= _MAX_DRAFTS:
                    break

            if self.enrich and out:
                for d in out[:8]:
                    try:
                        page_resp = await client.get(d.url or "")
                        if page_resp.status_code == 200:
                            enrich_from_jsonld(page_resp.text, d)
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("geekjob enrich %s: %s", d.external_id, exc)

        logger.info("geekjob: %d drafts", len(out))
        return out
