"""Коннектор вакансий из публичных Telegram-каналов (M7a).

Читает https://t.me/s/<username> — без Bot API и без админ-прав на публичных каналах.
Каталог: data/tg_job_channels.yaml.

Спека: docs/services/ingestion.md
"""

from __future__ import annotations

import re
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx
import yaml

from app.ingestion.schemas import OpportunityDraft
from app.observability.logging import get_logger

logger = get_logger("kabi.ingestion.tg_jobs")

_CHANNELS_PATH = Path(__file__).resolve().parents[3] / "data" / "tg_job_channels.yaml"
_UA = "KabiCareerManager/0.1 (personal; +https://t.me/YouUkabi_bot)"
_MSG_SPLIT = "tgme_widget_message_wrap"
_PERMALINK_RE = re.compile(r'href="(https://t\.me/([^/"\?]+)/(\d+))"')
_TEXT_RE = re.compile(
    r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
    re.S | re.I,
)
_HREF_RE = re.compile(r'href="(https?://[^"]+)"', re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def load_tg_config(path: Path | None = None) -> dict[str, Any]:
    data = yaml.safe_load((path or _CHANNELS_PATH).read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _strip_html(raw: str) -> str:
    text = unescape(raw.replace("&nbsp;", " "))
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<a[^>]*href=\"([^\"]+)\"[^>]*>", r"\1 ", text, flags=re.I)
    text = _TAG_RE.sub("", text)
    text = unquote(text.replace("&amp;", "&"))
    return _WS_RE.sub(" ", text).strip()


def _first_line_title(text: str) -> str:
    for line in text.split("\n"):
        line = line.strip(" ·—-|")
        if len(line) >= 8:
            return line[:200]
    return text[:120] or "Вакансия из Telegram"


def _external_job_url(text: str, html: str) -> str | None:
    """Предпочитаем внешнюю ссылку на вакансию, не linkedin/t.me."""
    candidates: list[str] = []
    for href in _HREF_RE.findall(html):
        url = unescape(href.replace("&amp;", "&"))
        low = url.lower()
        if "t.me/" in low or "telegram.org" in low:
            continue
        if any(x in low for x in ("linkedin.com", "instagram.com", "vk.com/wall")):
            continue
        candidates.append(url)
    # URLs plain in text
    for m in re.finditer(r"https?://[^\s\)\]\>\"']+", text):
        url = m.group(0).rstrip(".,;")
        low = url.lower()
        if "t.me/" in low or "linkedin.com" in low:
            continue
        if url not in candidates:
            candidates.append(url)
    return candidates[0] if candidates else None


def _relevant(text: str, needles: list[str]) -> bool:
    if not needles:
        return True
    low = text.lower()
    return any(n.lower() in low for n in needles if n)


def parse_channel_html(
    html: str,
    *,
    username: str,
    relevance_any: list[str],
    limit: int,
) -> list[OpportunityDraft]:
    drafts: list[OpportunityDraft] = []
    parts = html.split(_MSG_SPLIT)[1:]
    for block in parts:
        if len(drafts) >= limit:
            break
        pm = _PERMALINK_RE.search(block)
        if not pm:
            continue
        permalink, chan, msg_id = pm.group(1), pm.group(2), pm.group(3)
        if chan.lower() != username.lower():
            # иногда в блоке чужие репосты — берём permalink как есть
            pass
        tm = _TEXT_RE.search(block)
        if not tm:
            continue
        text = _strip_html(tm.group(1))
        if len(text) < 20:
            continue
        if not _relevant(text, relevance_any):
            continue
        title = _first_line_title(text)
        job_url = _external_job_url(text, block) or permalink
        ext_id = f"{username}_{msg_id}"
        drafts.append(
            OpportunityDraft(
                type="job",
                title=title,
                org=None,
                description=text[:2500],
                location=None,
                remote="удал" in text.lower() or "remote" in text.lower(),
                salary=None,
                url=job_url,
                source=f"tg_{username.lower()}",
                external_id=ext_id,
                tags=["telegram", username.lower()],
                meta={
                    "channel": username.lower(),
                    "permalink": permalink,
                    "kind": "tg_channel",
                },
            )
        )
    return drafts


class TelegramJobsConnector:
    """Публичные TG-каналы → OpportunityDraft."""

    source = "tg_jobs"

    def __init__(self, config_path: Path | None = None) -> None:
        self._cfg = load_tg_config(config_path)

    async def fetch(
        self, keywords: list[str], *, area: int | None = None
    ) -> list[OpportunityDraft]:
        del area  # TG не географический индекс
        channels = self._cfg.get("channels") or []
        limit = int(self._cfg.get("posts_per_channel") or 25)
        relevance = list(self._cfg.get("relevance_any") or [])
        # усиливаем фильтр ролями профиля
        for kw in keywords or []:
            if kw and kw.lower() not in {r.lower() for r in relevance}:
                relevance.append(kw)

        out: list[OpportunityDraft] = []
        async with httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": _UA},
            follow_redirects=True,
        ) as client:
            for ch in channels:
                if not isinstance(ch, dict):
                    continue
                username = str(ch.get("username") or "").strip().lstrip("@")
                if not username:
                    continue
                url = f"https://t.me/s/{username}"
                try:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        logger.warning(
                            "tg channel %s → HTTP %s", username, resp.status_code
                        )
                        continue
                    found = parse_channel_html(
                        resp.text,
                        username=username,
                        relevance_any=relevance,
                        limit=limit,
                    )
                    logger.info("tg_%s: %d posts kept", username, len(found))
                    out.extend(found)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("tg channel %s failed: %s", username, exc)
        return out
