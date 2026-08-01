"""Общий HTTP(S)/SOCKS-прокси для запросов к t.me.

С части облаков РФ TCP до t.me:443 недоступен — коннекторы TG/Getmatch
ходят через TG_HTTP_PROXY (Proxy6 SOCKS5 и т.п.).
"""

from __future__ import annotations

from app.config import settings


def tg_http_proxy() -> str | None:
    """URL прокси для httpx, или None если не задан."""
    raw = (settings.tg_http_proxy or "").strip()
    return raw or None
