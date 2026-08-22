"""Зависимости FastAPI: сессия БД, авторизованный пользователь, rate limit.

Спека: docs/services/miniapp.md §3, §6.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import InitData, InitDataError, verify_init_data
from app.config import settings
from app.db.models import Profile, User
from app.db.session import get_session
from app.observability.logging import get_logger
from app.services import profile as profile_service

logger = get_logger("kabi.api")

_AUTH_SCHEME = "tma"

_AUTH_MESSAGES = {
    "not_configured": "Mini App не настроен на сервере.",
    "malformed": "Не разобрал данные авторизации Telegram.",
    "no_hash": "Не разобрал данные авторизации Telegram.",
    "bad_signature": "Подпись Telegram не сошлась. Открой приложение заново.",
    "no_auth_date": "Не разобрал данные авторизации Telegram.",
    "expired": "Сессия устарела. Открой приложение заново.",
    "no_user": "Telegram не передал пользователя.",
}


def _unauthorized(code: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": code, "message": _AUTH_MESSAGES.get(code, "Нужна авторизация Telegram.")},
        headers={"WWW-Authenticate": _AUTH_SCHEME},
    )


def _no_profile() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "no_profile",
            "message": "Профиля пока нет. Загрузи резюме в чате с ботом.",
        },
    )


async def db_session() -> AsyncIterator[AsyncSession]:
    """Сессия на запрос: commit при успехе, rollback при исключении."""
    async with get_session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()


def current_init_data(request: Request) -> InitData:
    """Проверенный initData из заголовка `Authorization: tma <initData>`."""
    header = request.headers.get("authorization") or ""
    scheme, _, raw = header.partition(" ")
    if scheme.lower() != _AUTH_SCHEME or not raw.strip():
        raise _unauthorized("malformed")
    try:
        return verify_init_data(
            raw.strip(),
            bot_token=settings.telegram_bot_token,
            ttl_seconds=settings.miniapp_auth_ttl_seconds,
        )
    except InitDataError as exc:
        # Саму строку initData не логируем: в ней подпись и данные пользователя.
        logger.warning("miniapp_auth_deny code=%s path=%s", exc.code, request.url.path)
        raise _unauthorized(exc.code) from exc


@dataclass
class Actor:
    """Кто пришёл: Telegram-идентити + свои User/Profile (MU-A)."""

    init_data: InitData
    user: User
    profile: Profile | None

    @property
    def telegram_id(self) -> int:
        return self.init_data.user.id

    @property
    def owned_profile(self) -> Profile:
        """Профиль актора; 404 если онбординг в боте ещё не пройден."""
        if self.profile is None:
            raise _no_profile()
        return self.profile


async def current_actor(
    init_data: InitData = Depends(current_init_data),
    session: AsyncSession = Depends(db_session),
) -> Actor:
    user = await profile_service.get_or_create_user(session, init_data.user.id)
    profile = await profile_service.get_profile(session, user.id)
    return Actor(init_data=init_data, user=user, profile=profile)


async def current_profile(actor: Actor = Depends(current_actor)) -> Actor:
    """То же, но 404 если профиля ещё нет (не прошёл онбординг в боте)."""
    if actor.profile is None:
        raise _no_profile()
    return actor


class RateLimiter:
    """Скользящее окно на пользователя. Предохранитель, не защита от DDoS."""

    def __init__(self, *, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[int, deque[float]] = {}

    def check(self, key: int, *, now: float | None = None) -> bool:
        moment = time.monotonic() if now is None else now
        hits = self._hits.setdefault(key, deque())
        while hits and moment - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(moment)
        return True


expensive_limiter = RateLimiter(limit=5, window_seconds=300)


def rate_limit_expensive(actor: Actor = Depends(current_profile)) -> Actor:
    """Для ручек, которые ходят в сеть или в LLM."""
    if not expensive_limiter.check(actor.telegram_id):
        logger.warning("miniapp_rate_limited tg=%s", actor.telegram_id)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "rate_limited",
                "message": "Слишком часто. Подожди пару минут.",
            },
        )
    return actor
