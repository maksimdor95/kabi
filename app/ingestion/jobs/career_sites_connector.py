"""Коннектор карьерных сайтов компаний (M7c).

Yandex — публичный JSON API. Остальные — HTML-листинг + фильтр по ролям.
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


def load_career_config(path: Path | None = None) -> dict[str, Any]:
    data = yaml.safe_load((path or _SITES_PATH).read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _clean(text: str) -> str:
    text = unescape(_TAG_RE.sub(" ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def _relevant(text: str, needles: list[str]) -> bool:
    if not needles:
        return True
    low = text.lower()
    return any(n.lower() in low for n in needles if n)


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
    while cursor_url and seen < 120:
        resp = await client.get(cursor_url)
        if resp.status_code != 200:
            logger.warning("yandex api → HTTP %s", resp.status_code)
            break
        payload = resp.json()
        for item in payload.get("results") or []:
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
            loc = ", ".join(c.get("name") for c in cities if isinstance(c, dict) and c.get("name"))
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
        # next иногда на внутренний хост — не ходим туда
        if not nxt or "yandex.ru" not in str(nxt):
            break
        cursor_url = str(nxt).replace("http://", "https://")
        if "femida.yandex-team.ru" in cursor_url:
            break
    return drafts


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
    path_re = re.compile(path_regex, re.I) if path_regex else None
    excludes = [e.lower() for e in (path_exclude or []) if e]
    for href, anchor in _HREF_RE.findall(html):
        href = unescape(href.strip())
        if href.startswith("#") or href.startswith("javascript:"):
            continue
        full = urljoin(list_url, href)
        low = full.lower()
        path = urlparse(full).path or ""
        if excludes and any(ex in low or ex in path.lower() for ex in excludes):
            continue
        if path_re is not None:
            if not path_re.search(path):
                continue
        elif not any(frag.lower() in low for frag in link_contains):
            continue
        # aria-label иногда в соседнем атрибуте того же <a> — якорь уже в group
        title = _clean(anchor)
        if not title or len(title) < 4:
            # slug из path: /vacancies/foo/123/ → foo
            parts = [p for p in path.strip("/").split("/") if p and not p.isdigit()]
            title = _clean((parts[-1] if parts else path).replace("-", " "))
        if len(title) < 4:
            continue
        if not _relevant(title + " " + full, relevance):
            continue
        if full in seen:
            continue
        seen.add(full)
        # стабильный id: последний числовой сегмент или hash
        nums = re.findall(r"/(\d{3,})/?", path)
        ext = nums[-1] if nums else str(abs(hash(full)) % (10**12))
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
                    if kind == "yandex_api":
                        found = await _fetch_yandex(client, site, relevance)
                    else:
                        list_url = str(site.get("list_url") or "")
                        if not list_url:
                            continue
                        ssl_verify = bool(site.get("ssl_verify", True))
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
                                "career %s → HTTP %s", site_id, resp.status_code
                            )
                            continue
                        found = parse_html_list(
                            resp.text,
                            site_id=site_id,
                            company=str(site.get("name") or site_id),
                            list_url=list_url,
                            link_contains=list(site.get("link_contains") or ["vacancy"]),
                            relevance=relevance,
                            path_regex=site.get("path_regex"),
                            path_exclude=list(site.get("path_exclude") or []),
                        )
                    logger.info("career_%s: %d drafts", site_id, len(found))
                    out.extend(found)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("career %s failed: %s", site_id, exc)
        return out
