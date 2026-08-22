"""FastAPI-приложение: health-check и API Telegram Mini App.

Спека: docs/services/miniapp.md, docs/architecture/overview.md
Схему БД этот процесс не мигрирует — этим владеет `bot.main` / `scripts/migrate.py`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router
from app.config import settings
from app.observability.logging import get_logger

logger = get_logger("kabi.api")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

# Mini App живёт во фрейме Telegram Web и в webview нативных клиентов,
# поэтому X-Frame-Options не ставим — ограничиваем предков через CSP.
_CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self' https://telegram.org",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: https:",
        "connect-src 'self'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors https://web.telegram.org https://*.telegram.org tg://",
    ]
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if not settings.telegram_bot_token:
        logger.warning("api_start: TELEGRAM_BOT_TOKEN пуст — авторизация Mini App невозможна")
    logger.info(
        "api_start env=%s miniapp_enabled=%s web_dir=%s",
        settings.app_env,
        settings.miniapp_enabled,
        WEB_DIR if WEB_DIR.is_dir() else "—",
    )
    yield


app = FastAPI(title="Kabi", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def security_headers(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    response = await call_next(request)
    response.headers.setdefault("Content-Security-Policy", _CSP)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
    """Единый формат ошибки: {"code", "message"} — фронт не разбирает detail."""
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        body = detail
    else:
        body = {"code": f"http_{exc.status_code}", "message": str(detail)}
    return JSONResponse(status_code=exc.status_code, content=body, headers=exc.headers)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(api_router)

if WEB_DIR.is_dir():
    # Монтируем последним: этот mount ловит все не-API пути.
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
