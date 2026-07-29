"""Утилиты качества URL для talks/CFP."""

from __future__ import annotations

from urllib.parse import urlparse


def is_actionable_cfp_url(url: str | None, *, homepage: str | None = None) -> bool:
    """True только если URL похож на страницу заявки, а не на корень сайта.

    Корни вроде https://egconf.io/ или https://www.youtube.com/ — не форма заявки.
    """
    if not url or not str(url).strip():
        return False
    raw = str(url).strip()
    try:
        parsed = urlparse(raw)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    path = (parsed.path or "").strip("/")
    # Нет пути глубже корня — это главная, не CFP.
    if not path:
        return False
    if homepage:
        try:
            home = urlparse(str(homepage).strip())
            same_host = parsed.netloc.lower().removeprefix("www.") == home.netloc.lower().removeprefix(
                "www."
            )
            if same_host and not (home.path or "").strip("/") and path in {
                "index.html",
                "index.htm",
            }:
                return False
        except ValueError:
            pass
    return True
