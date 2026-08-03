"""Коннектор карьерных сайтов компаний (M7c).

Yandex + волна A (Alfa/WB/Sber/MTS) — публичные JSON API (порт из Leo).
Avito/VK — HTML-листинг. Т-Банк — HTML SSR IT-листингов (каталог all — SPA).
Ozon выкл. (antibot).

Каталог: data/career_sites.yaml.
Спека: docs/services/ingestion.md
"""

from __future__ import annotations

import re
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
import yaml

from app.ingestion.schemas import OpportunityDraft
from app.observability.logging import get_logger

logger = get_logger("kabi.ingestion.career_sites")

_SITES_PATH = Path(__file__).resolve().parents[3] / "data" / "career_sites.yaml"
_UA = "KabiCareerManager/0.1 (personal; +https://t.me/YouUkabi_bot)"
_HREF_RE = re.compile(
    r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
    re.S | re.I,
)
_TAG_RE = re.compile(r"<[^>]+>")
_MAX_PER_SITE = 40


def load_career_config(path: Path | None = None) -> dict[str, Any]:
    data = yaml.safe_load((path or _SITES_PATH).read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _clean(text: str) -> str:
    text = unescape(_TAG_RE.sub(" ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def _relevant(text: str, needles: list[str]) -> bool:
    """Substring match; пустой needles = всё подходит."""
    if not needles:
        return True
    low = text.lower()
    for n in needles:
        if not n:
            continue
        # токены ≥4 — мягче, чем целая фраза (как фикс в Leo smoke)
        parts = [p for p in re.split(r"[\s/|,]+", n.lower()) if len(p) >= 4]
        if parts and any(p in low for p in parts):
            return True
        if n.lower() in low:
            return True
    return False


def _remote_from_text(*parts: str) -> bool:
    blob = " ".join(p for p in parts if p).lower()
    return any(x in blob for x in ("remote", "удал", "гибрид", "hybrid"))


# --- JSON API (волна A / Yandex) -------------------------------------------------


async def _fetch_yandex(
    client: httpx.AsyncClient,
    site: dict[str, Any],
    relevance: list[str],
) -> list[OpportunityDraft]:
    base = str(site.get("list_url") or "https://yandex.ru/jobs/api/publications")
    tmpl = str(
        site.get("vacancy_url_template")
        or "https://yandex.ru/jobs/vacancies/{slug}"
    )
    drafts: list[OpportunityDraft] = []
    cursor_url = f"{base}?page_size=40"
    seen = 0
    while cursor_url and seen < 120 and len(drafts) < _MAX_PER_SITE:
        resp = await client.get(cursor_url)
        if resp.status_code != 200:
            logger.warning("yandex api → HTTP %s", resp.status_code)
            break
        payload = resp.json()
        for item in payload.get("results") or []:
            if len(drafts) >= _MAX_PER_SITE:
                break
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            blob = title + " " + str(item.get("short_summary") or "")
            if not _relevant(blob, relevance):
                continue
            slug = item.get("publication_slug_url") or ""
            url = item.get("redirect_url") or (
                tmpl.format(slug=slug) if slug else None
            )
            vac = item.get("vacancy") or {}
            cities = vac.get("cities") or []
            loc = ", ".join(
                c.get("name") for c in cities if isinstance(c, dict) and c.get("name")
            )
            modes = vac.get("work_modes") or []
            remote = any(
                "remote" in str(m).lower() or "удал" in str(m).lower() for m in modes
            )
            ext = str(item.get("id") or slug)
            drafts.append(
                OpportunityDraft(
                    type="job",
                    title=title,
                    org="Яндекс",
                    description=(item.get("short_summary") or title)[:2000],
                    location=loc or None,
                    remote=remote,
                    url=url,
                    source="career_yandex",
                    external_id=ext,
                    tags=["career_site", "yandex"],
                    meta={"kind": "career_site", "company": "yandex"},
                )
            )
        seen += len(payload.get("results") or [])
        nxt = payload.get("next")
        if not nxt or "yandex.ru" not in str(nxt):
            break
        cursor_url = str(nxt).replace("http://", "https://")
        if "femida.yandex-team.ru" in cursor_url:
            break
    return drafts


async def _fetch_alfa(
    client: httpx.AsyncClient,
    site: dict[str, Any],
    relevance: list[str],
) -> list[OpportunityDraft]:
    """job.alfabank.ru/api/vacancies — нужен take; SSL часто insecure."""
    base = str(site.get("list_url") or "https://job.alfabank.ru/api/vacancies")
    drafts: list[OpportunityDraft] = []
    seen: set[str] = set()
    take = 50
    keywords = relevance[:5] or [""]
    ssl_verify = bool(site.get("ssl_verify", False))

    async def _get(params: dict[str, Any]) -> httpx.Response:
        if ssl_verify:
            return await client.get(base, params=params)
        async with httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": _UA,
                "Accept": "application/json",
                "Referer": "https://job.alfabank.ru/vacancies",
            },
            follow_redirects=True,
            verify=False,
        ) as insecure:
            return await insecure.get(base, params=params)

    for text in keywords:
        if len(drafts) >= _MAX_PER_SITE:
            break
        skip = 0
        total = float("inf")
        while skip < total and len(drafts) < _MAX_PER_SITE and skip < _MAX_PER_SITE * 2:
            params: dict[str, Any] = {"take": take, "skip": skip}
            if text:
                params["text"] = text
            resp = await _get(params)
            if resp.status_code != 200:
                logger.warning("alfa api → HTTP %s", resp.status_code)
                break
            payload = resp.json()
            items = payload.get("items") or []
            total = float(payload["total"]) if isinstance(payload.get("total"), int) else len(items)
            if not items:
                break
            for item in items:
                if len(drafts) >= _MAX_PER_SITE:
                    break
                title = str(item.get("name") or "").strip()
                vid = str(item.get("id") or "").strip()
                if not title or not vid:
                    continue
                slug = item.get("slug") or ""
                if isinstance(slug, str) and slug.startswith("/"):
                    url = f"https://job.alfabank.ru/vacancies{slug}"
                elif slug:
                    url = f"https://job.alfabank.ru/vacancies/{slug}"
                else:
                    url = f"https://job.alfabank.ru/vacancies/{vid}"
                if url in seen:
                    continue
                seen.add(url)
                desc = _clean(
                    item.get("descriptionText")
                    or item.get("description")
                    or item.get("duties")
                    or title
                )
                drafts.append(
                    OpportunityDraft(
                        type="job",
                        title=title[:200],
                        org="Альфа-Банк",
                        description=desc[:2500],
                        remote=_remote_from_text(str(slug), desc),
                        url=url,
                        source="career_alfa",
                        external_id=vid,
                        tags=["career_site", "alfa"],
                        meta={"kind": "career_api", "company": "alfa"},
                    )
                )
            skip += take
            if len(items) < take:
                break
    return drafts


async def _fetch_wb(
    client: httpx.AsyncClient,
    site: dict[str, Any],
    relevance: list[str],
) -> list[OpportunityDraft]:
    """career.rwb.ru CRM public vacancies."""
    base = str(site.get("api_base") or "https://career.rwb.ru")
    list_url = str(
        site.get("list_url") or f"{base}/crm-api/api/v1/pub/vacancies"
    )
    drafts: list[OpportunityDraft] = []
    seen: set[str] = set()
    queries = relevance[:5] or [""]

    for title_q in queries:
        if len(drafts) >= _MAX_PER_SITE:
            break
        params: dict[str, Any] = {"limit": min(50, _MAX_PER_SITE), "offset": 0}
        if title_q:
            params["title"] = title_q
        resp = await client.get(
            list_url,
            params=params,
            headers={"Accept": "application/json", "Referer": f"{base}/"},
        )
        if resp.status_code != 200:
            logger.warning("wb api → HTTP %s", resp.status_code)
            continue
        payload = resp.json()
        items = ((payload.get("data") or {}).get("items")) or []
        for item in items:
            if len(drafts) >= _MAX_PER_SITE:
                break
            title = str(item.get("name") or "").strip()
            vid = item.get("id")
            if not title or vid is None:
                continue
            url = f"{base}/vacancies/{vid}"
            if url in seen:
                continue
            seen.add(url)
            emp = " ".join(
                str(e.get("title") or "")
                for e in (item.get("employment_types") or [])
                if isinstance(e, dict)
            )
            desc = " · ".join(
                x
                for x in (
                    item.get("direction_role_title"),
                    item.get("direction_title"),
                )
                if x
            ) or title
            drafts.append(
                OpportunityDraft(
                    type="job",
                    title=title[:200],
                    org="Wildberries",
                    description=str(desc)[:2000],
                    location=item.get("city_title") or None,
                    remote=_remote_from_text(emp),
                    url=url,
                    source="career_wb",
                    external_id=str(vid),
                    tags=["career_site", "wb"],
                    meta={"kind": "career_api", "company": "wildberries"},
                )
            )
    return drafts


async def _fetch_sber(
    client: httpx.AsyncClient,
    site: dict[str, Any],
    relevance: list[str],
) -> list[OpportunityDraft]:
    """Sber publications gateway — client-side keyword filter."""
    list_url = str(
        site.get("list_url")
        or "https://rabota.sber.ru/public/app-candidate-public-api-gateway/api/v1/publications"
    )
    drafts: list[OpportunityDraft] = []
    seen: set[str] = set()
    take = 50
    skip = 0
    total = float("inf")
    pages = 0

    def _slugify(title: str) -> str:
        s = re.sub(r"[^a-z0-9а-яё]+", "-", title.lower(), flags=re.I)
        return s.strip("-")[:80] or "vacancy"

    while skip < total and len(drafts) < _MAX_PER_SITE and pages < 8:
        resp = await client.get(
            list_url,
            params={"skip": skip, "take": take},
            headers={
                "Accept": "application/json",
                "Referer": "https://rabota.sber.ru/search/",
            },
        )
        if resp.status_code != 200:
            logger.warning("sber api → HTTP %s", resp.status_code)
            break
        payload = resp.json()
        data = payload.get("data") or {}
        rows = data.get("vacancies") or []
        total = float(data["total"]) if isinstance(data.get("total"), int) else len(rows)
        pages += 1
        if not rows:
            break
        for item in rows:
            if len(drafts) >= _MAX_PER_SITE:
                break
            title = str(item.get("title") or "").strip()
            iid = item.get("internalId")
            if not title or iid is None:
                continue
            blob = " ".join(
                str(x)
                for x in (
                    title,
                    item.get("specialization"),
                    item.get("introduction"),
                    item.get("duties"),
                    item.get("requirements"),
                )
                if x
            )
            if not _relevant(blob, relevance):
                continue
            url = f"https://rabota.sber.ru/search/{_slugify(title)}-{iid}/"
            if url in seen:
                continue
            seen.add(url)
            desc = _clean(item.get("introduction") or item.get("duties") or title)
            salary = None
            smin, smax = item.get("salary_min"), item.get("salary_max")
            if smin is not None or smax is not None:
                salary = {"min": smin, "max": smax, "currency": "RUR"}
            drafts.append(
                OpportunityDraft(
                    type="job",
                    title=title[:200],
                    org=str(item.get("company") or "Сбер"),
                    description=desc[:2500],
                    location=item.get("city") or item.get("region") or None,
                    remote=_remote_from_text(blob),
                    salary=salary,
                    url=url,
                    source="career_sber",
                    external_id=str(iid),
                    tags=["career_site", "sber"],
                    meta={"kind": "career_api", "company": "sber"},
                )
            )
        skip += take
    return drafts


async def _fetch_mts(
    client: httpx.AsyncClient,
    site: dict[str, Any],
    relevance: list[str],
) -> list[OpportunityDraft]:
    list_url = str(site.get("list_url") or "https://job.mts.ru/api/v2/vacancies")
    drafts: list[OpportunityDraft] = []
    seen: set[str] = set()
    page = 1
    page_count = 1
    page_size = 50

    while page <= page_count and len(drafts) < _MAX_PER_SITE and page <= 8:
        resp = await client.get(
            list_url,
            params={"pagination[page]": page, "pagination[pageSize]": page_size},
            headers={
                "Accept": "application/json",
                "Origin": "https://job.mts.ru",
                "Referer": "https://job.mts.ru/vacancies",
            },
        )
        if resp.status_code != 200:
            logger.warning("mts api → HTTP %s", resp.status_code)
            break
        payload = resp.json()
        rows = payload.get("data") or []
        meta = (payload.get("meta") or {}).get("pagination") or {}
        page_count = int(meta.get("pageCount") or page)
        for item in rows:
            if len(drafts) >= _MAX_PER_SITE:
                break
            title = str(item.get("title") or "").strip()
            slug = str(item.get("slug") or "").strip()
            if not title or not slug:
                continue
            org = (item.get("organization") or {}).get("title") or "МТС"
            cats = " ".join(
                str(c.get("title") or "")
                for c in (item.get("categories") or [])
                if isinstance(c, dict)
            )
            if not _relevant(f"{title} {org} {cats}", relevance):
                continue
            url = f"https://job.mts.ru/vacancy/{slug}"
            if url in seen:
                continue
            seen.add(url)
            formats = " ".join(
                str(f.get("title") or "")
                for f in (item.get("workFormats") or [])
                if isinstance(f, dict)
            )
            salary = None
            smin, smax = item.get("salaryFrom"), item.get("salaryTo")
            if smin is not None or smax is not None:
                cur = (item.get("currency") or {}).get("title") or "RUR"
                if cur == "RUB":
                    cur = "RUR"
                salary = {"min": smin, "max": smax, "currency": cur}
            drafts.append(
                OpportunityDraft(
                    type="job",
                    title=title[:200],
                    org=str(org),
                    description=title,
                    location=(item.get("region") or {}).get("title"),
                    remote=_remote_from_text(formats),
                    salary=salary,
                    url=url,
                    source="career_mts",
                    external_id=str(item.get("documentId") or slug),
                    tags=["career_site", "mts"],
                    meta={"kind": "career_api", "company": "mts"},
                )
            )
        page += 1
        if not rows:
            break
    return drafts


_JSON_FETCHERS = {
    "yandex_api": _fetch_yandex,
    "alfa_api": _fetch_alfa,
    "wb_api": _fetch_wb,
    "sber_api": _fetch_sber,
    "mts_api": _fetch_mts,
}


# --- HTML -----------------------------------------------------------------------


_GENERIC_ANCHORS = {
    "откликнуться",
    "подробнее",
    "смотреть",
    "открыть",
    "вакансия",
    "читать",
    "далее",
    "more",
    "apply",
    "x",
    "y",
    "z",
}


def _title_from_path(path: str, anchor: str) -> str:
    title = _clean(anchor)
    if (
        title
        and len(title) >= 4
        and "http" not in title.lower()
        and title.lower() not in _GENERIC_ANCHORS
    ):
        return title[:200]
    # /career/it/vacancy/moscow/seo-slug/uuid/ → seo-slug
    parts = [p for p in path.strip("/").split("/") if p]
    slug = ""
    if "vacancy" in parts:
        try:
            i = parts.index("vacancy")
            # city then slug then uuid
            if i + 2 < len(parts):
                slug = parts[i + 2]
        except ValueError:
            slug = ""
    if not slug:
        slug = next(
            (p for p in reversed(parts) if not re.fullmatch(r"[0-9a-f-]{8,}", p, re.I)),
            path,
        )
    return _clean(slug.replace("-", " "))[:200]


def parse_html_list(
    html: str,
    *,
    site_id: str,
    company: str,
    list_url: str,
    link_contains: list[str],
    relevance: list[str],
    path_regex: str | None = None,
    path_exclude: list[str] | None = None,
) -> list[OpportunityDraft]:
    drafts: list[OpportunityDraft] = []
    seen: set[str] = set()
    seen_ext: set[str] = set()
    path_re = re.compile(path_regex, re.I) if path_regex else None
    excludes = [e.lower() for e in (path_exclude or []) if e]

    # (full_url, anchor_text) — <a href> + сырые path из JSON/SSR (Т-Банк).
    candidates: list[tuple[str, str]] = []
    for href, anchor in _HREF_RE.findall(html):
        candidates.append((unescape(href.strip()), anchor))
    if path_re is not None:
        for m in path_re.finditer(html):
            candidates.append((m.group(0), ""))

    for href, anchor in candidates:
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue
        full = urljoin(list_url, href)
        # нормализуем path-only матчи без схемы
        if full.startswith("/") and list_url:
            full = urljoin(list_url, full)
        full = full.split("?")[0].rstrip("/") + "/"
        low = full.lower()
        path = urlparse(full).path or ""
        if excludes and any(ex in low or ex in path.lower() for ex in excludes):
            continue
        if path_re is not None:
            if not path_re.search(path):
                continue
        elif not any(frag.lower() in low for frag in link_contains):
            continue
        title = _title_from_path(path, anchor)
        if len(title) < 4:
            continue
        if not _relevant(title + " " + full, relevance):
            continue
        uuid_m = re.search(r"/([0-9a-f]{8}-[0-9a-f-]{27,})/?$", path, re.I)
        nums = re.findall(r"/(\d{3,})/?", path)
        if uuid_m:
            ext = uuid_m.group(1)
        elif nums:
            ext = nums[-1]
        else:
            ext = str(abs(hash(full)) % (10**12))
        if full in seen or ext in seen_ext:
            # предпочитаем вариант с человекочитаемым anchor
            continue
        seen.add(full)
        seen_ext.add(str(ext))
        drafts.append(
            OpportunityDraft(
                type="job",
                title=title[:200],
                org=company,
                description=title,
                url=full,
                source=f"career_{site_id}",
                external_id=str(ext),
                tags=["career_site", site_id],
                meta={"kind": "career_site", "company": site_id},
            )
        )
    return drafts


class CareerSitesConnector:
    source = "career_sites"

    def __init__(self, config_path: Path | None = None) -> None:
        self._cfg = load_career_config(config_path)

    async def fetch(
        self, keywords: list[str], *, area: int | None = None
    ) -> list[OpportunityDraft]:
        del area
        relevance = list(self._cfg.get("title_relevance_any") or [])
        for kw in keywords or []:
            if kw and kw.lower() not in {r.lower() for r in relevance}:
                relevance.append(kw)

        out: list[OpportunityDraft] = []
        sites = [s for s in (self._cfg.get("sites") or []) if isinstance(s, dict)]
        async with httpx.AsyncClient(
            timeout=35.0,
            headers={"User-Agent": _UA, "Accept-Language": "ru,en;q=0.8"},
            follow_redirects=True,
            verify=True,
        ) as client:
            for site in sites:
                if not site.get("enabled", True):
                    continue
                site_id = str(site.get("id") or "unknown")
                kind = str(site.get("kind") or "html_list")
                try:
                    fetcher = _JSON_FETCHERS.get(kind)
                    if fetcher is not None:
                        found = await fetcher(client, site, relevance)
                    else:
                        list_urls = [
                            str(u)
                            for u in (
                                site.get("list_urls")
                                or ([site.get("list_url")] if site.get("list_url") else [])
                            )
                            if u
                        ]
                        if not list_urls:
                            continue
                        ssl_verify = bool(site.get("ssl_verify", True))
                        found: list[OpportunityDraft] = []
                        seen_ext: set[str] = set()
                        for list_url in list_urls:
                            if ssl_verify:
                                resp = await client.get(list_url)
                            else:
                                async with httpx.AsyncClient(
                                    timeout=35.0,
                                    headers={
                                        "User-Agent": _UA,
                                        "Accept-Language": "ru,en;q=0.8",
                                    },
                                    follow_redirects=True,
                                    verify=False,
                                ) as insecure:
                                    resp = await insecure.get(list_url)
                            if resp.status_code != 200:
                                logger.warning(
                                    "career %s → HTTP %s (%s)",
                                    site_id,
                                    resp.status_code,
                                    list_url,
                                )
                                continue
                            page_drafts = parse_html_list(
                                resp.text,
                                site_id=site_id,
                                company=str(site.get("name") or site_id),
                                list_url=list_url,
                                link_contains=list(
                                    site.get("link_contains") or ["vacancy"]
                                ),
                                relevance=relevance,
                                path_regex=site.get("path_regex"),
                                path_exclude=list(site.get("path_exclude") or []),
                            )
                            for d in page_drafts:
                                if d.external_id in seen_ext:
                                    continue
                                seen_ext.add(str(d.external_id))
                                found.append(d)
                                if len(found) >= _MAX_PER_SITE:
                                    break
                            if len(found) >= _MAX_PER_SITE:
                                break
                    logger.info("career_%s: %d drafts", site_id, len(found))
                    out.extend(found)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("career %s failed: %s", site_id, exc)
        return out
