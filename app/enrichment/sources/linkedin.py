"""Источник обогащения: LinkedIn (парсинг по ссылке пользователя).

Осознанное нарушение ToS LinkedIn для personal MVP.
Обход login-wall (каскад):
  1) прямой запрос + browser UA
  2) guest-сессия (прогрев cookies) + public_profile URL
  3) cookie li_at из .env (LINKEDIN_LI_AT) — если пользователь дал свою сессию
  4) Google Web Cache
  5) Wayback Machine (последний снимок)

Чужие профили по имени не ищем (hard rule №5).
"""

from __future__ import annotations

import json
import re
from urllib.parse import quote

import httpx

from app.config import settings
from app.enrichment.html_utils import html_to_text
from app.enrichment.signals import ProfileSignals
from app.llm import client as llm
from app.observability.logging import get_logger

logger = get_logger("kabi.enrichment.linkedin")

_LI_RE = re.compile(r"https?://(?:[\w.-]+\.)?linkedin\.com/(?:in|pub)/", re.I)
_SLUG_RE = re.compile(r"linkedin\.com/(?:in|pub)/([^/?#]+)", re.I)

_WALL_MARKERS = (
    "sign in",
    "join now",
    "authwall",
    "session redirect",
    "войдите",
    "зарегистрируйтесь",
    "join linkedin",
    "authwall-join-form",
)

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
}

_SYSTEM = (
    "Ты извлекаешь сигналы карьерного профиля из текста публичной страницы LinkedIn. "
    "Возвращай только факты из текста. Ответ — строго JSON."
)

_PROMPT = """Из текста страницы LinkedIn-профиля извлеки JSON:
- speaking_topics: темы, на которых человек специализируется / может выступать (массив; [] если неясно)
- extra_skills: навыки (массив)
- job_search_status: "active" | "passive" | "top_only" | null
  (если явно указан Open to Work / actively looking → active; иначе null)

Текст:
\"\"\"
{text}
\"\"\"
"""


class LinkedInSource:
    name = "linkedin"

    def matches(self, url: str) -> bool:
        return bool(_LI_RE.search(url))

    async def fetch(self, url: str) -> ProfileSignals:
        text, via = await _fetch_with_fallbacks(url)
        if not text:
            return ProfileSignals(
                source_links=[url],
                notes=[
                    "LinkedIn: не удалось обойти login-wall "
                    "(прямой / guest / cache / wayback). "
                    "Можно положить LINKEDIN_LI_AT в .env (cookie из браузера)."
                ],
            )
        if _looks_like_auth_wall(text):
            logger.warning("linkedin_still_wall via=%s url=%s", via, url)
            return ProfileSignals(
                source_links=[url],
                notes=[
                    f"LinkedIn: login-wall даже после обходов (via={via}). "
                    "Положи LINKEDIN_LI_AT в .env или пришли текст About."
                ],
            )

        logger.info("linkedin_ok via=%s chars=%d url=%s", via, len(text), url)
        data = await llm.complete_json(
            _PROMPT.format(text=text[:15000]),
            system=_SYSTEM,
            tier="cheap",
        )
        if not isinstance(data, dict):
            return ProfileSignals(source_links=[url], notes=[f"LinkedIn прочитан via={via}, но JSON не разобран"])
        status = data.get("job_search_status")
        if status not in {"active", "passive", "top_only", None}:
            status = None
        notes = [f"LinkedIn прочитан via={via}"] if via != "direct" else []
        return ProfileSignals(
            speaking_topics=list(data.get("speaking_topics") or []),
            extra_skills=list(data.get("extra_skills") or []),
            job_search_status=status,
            source_links=[url],
            notes=notes,
        )


def _looks_like_auth_wall(text: str) -> bool:
    lower = text.lower()
    hits = sum(1 for m in _WALL_MARKERS if m in lower)
    # Короткий текст с маркерами входа ИЛИ явный authwall в разметке
    if "authwall" in lower:
        return True
    return hits >= 2 and len(text) < 3500


def _normalize_profile_url(url: str) -> str:
    m = _SLUG_RE.search(url)
    if not m:
        return url.split("?")[0].rstrip("/")
    slug = m.group(1).rstrip("/")
    return f"https://www.linkedin.com/in/{slug}"


def _meta_and_jsonld(html: str) -> str:
    parts: list[str] = []
    for pattern in (
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']',
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:description["\']',
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        r"<title>([^<]+)</title>",
    ):
        m = re.search(pattern, html, re.I)
        if m:
            parts.append(m.group(1).strip())

    for block in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.I | re.S,
    ):
        try:
            data = json.loads(block.strip())
            parts.append(json.dumps(data, ensure_ascii=False)[:4000])
        except json.JSONDecodeError:
            continue
    return "\n".join(parts)


def _html_to_profile_text(html: str) -> str:
    meta = _meta_and_jsonld(html)
    body = html_to_text(html)
    return "\n".join(p for p in (meta, body) if p).strip()


async def _get_html(
    client: httpx.AsyncClient,
    url: str,
    *,
    cookies: dict[str, str] | None = None,
) -> str:
    resp = await client.get(url, headers=_BROWSER_HEADERS, cookies=cookies or {})
    if resp.status_code != 200:
        logger.info("linkedin_http status=%s url=%s", resp.status_code, url)
        return ""
    return resp.text


async def _strategy_direct(client: httpx.AsyncClient, profile_url: str) -> tuple[str, str]:
    html = await _get_html(client, profile_url)
    text = _html_to_profile_text(html) if html else ""
    return text, "direct"


async def _strategy_guest(client: httpx.AsyncClient, profile_url: str) -> tuple[str, str]:
    """Прогрев guest-cookies на главной, затем публичный URL профиля."""
    await client.get("https://www.linkedin.com/", headers=_BROWSER_HEADERS)
    public = f"{profile_url}?trk=public_profile"
    html = await _get_html(client, public)
    text = _html_to_profile_text(html) if html else ""
    return text, "guest"


async def _strategy_session_cookie(
    client: httpx.AsyncClient, profile_url: str
) -> tuple[str, str]:
    li_at = (settings.linkedin_li_at or "").strip()
    if not li_at:
        return "", "cookie"
    cookies = {"li_at": li_at}
    # Иногда нужен ещё JSESSIONID — если положили через LINKEDIN_JSESSIONID
    jsid = (settings.linkedin_jsessionid or "").strip()
    if jsid:
        cookies["JSESSIONID"] = jsid if jsid.startswith('"') else f'"{jsid}"'
    html = await _get_html(client, profile_url, cookies=cookies)
    text = _html_to_profile_text(html) if html else ""
    return text, "cookie"


async def _strategy_google_cache(client: httpx.AsyncClient, profile_url: str) -> tuple[str, str]:
    # webcache часто отдаёт устаревший, но публичный снимок без login-wall
    cached = (
        "https://webcache.googleusercontent.com/search?q=cache:"
        + quote(profile_url.replace("https://", "").replace("http://", ""), safe="")
        + "&strip=0"
    )
    html = await _get_html(client, cached)
    text = _html_to_profile_text(html) if html else ""
    return text, "google_cache"


async def _strategy_wayback(client: httpx.AsyncClient, profile_url: str) -> tuple[str, str]:
    avail = "https://archive.org/wayback/available"
    try:
        resp = await client.get(avail, params={"url": profile_url}, headers=_BROWSER_HEADERS, timeout=20)
        data = resp.json()
        snap = (data.get("archived_snapshots") or {}).get("closest") or {}
        snap_url = snap.get("url")
        if not snap_url:
            # fallback: CDX последний 200
            cdx = await client.get(
                "https://web.archive.org/cdx/search/cdx",
                params={
                    "url": profile_url,
                    "output": "json",
                    "filter": "statuscode:200",
                    "limit": 1,
                    "fl": "timestamp,original",
                },
                headers=_BROWSER_HEADERS,
                timeout=20,
            )
            rows = cdx.json()
            if isinstance(rows, list) and len(rows) >= 2:
                ts, original = rows[1][0], rows[1][1]
                snap_url = f"https://web.archive.org/web/{ts}/{original}"
        if not snap_url:
            return "", "wayback"
        html = await _get_html(client, snap_url)
        text = _html_to_profile_text(html) if html else ""
        return text, "wayback"
    except Exception:  # noqa: BLE001
        logger.exception("linkedin_wayback_failed")
        return "", "wayback"


async def _fetch_with_fallbacks(url: str) -> tuple[str, str]:
    """Вернуть (text, via). via — какая стратегия сработала."""
    profile_url = _normalize_profile_url(url)
    strategies = (
        _strategy_direct,
        _strategy_guest,
        _strategy_session_cookie,
        _strategy_google_cache,
        _strategy_wayback,
    )
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for strategy in strategies:
            try:
                text, via = await strategy(client, profile_url)
            except Exception:  # noqa: BLE001
                logger.exception("linkedin_strategy_failed name=%s", strategy.__name__)
                continue
            if text and not _looks_like_auth_wall(text):
                # Минимум смысла: не только «LinkedIn» в title
                if len(text) < 80 and "linkedin" in text.lower():
                    continue
                return text, via
            logger.info(
                "linkedin_strategy_skip name=%s chars=%d wall=%s",
                via,
                len(text or ""),
                _looks_like_auth_wall(text or ""),
            )
    return "", "none"
