"""Проверка подписи Telegram Mini App `initData`.

Чистые функции без FastAPI — чтобы тестировать криптографию отдельно от HTTP.
Спека и правила: docs/services/miniapp.md §3.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from operator import itemgetter
from typing import Literal
from urllib.parse import parse_qsl, urlencode

DEFAULT_TTL_SECONDS = 24 * 60 * 60

AuthErrorCode = Literal[
    "not_configured",
    "malformed",
    "no_hash",
    "bad_signature",
    "no_auth_date",
    "expired",
    "no_user",
]


class InitDataError(Exception):
    """Отказ авторизации с машинным кодом причины."""

    def __init__(self, code: AuthErrorCode, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


@dataclass(frozen=True)
class WebAppUser:
    id: int
    first_name: str = ""
    last_name: str = ""
    username: str = ""
    language_code: str = ""
    is_premium: bool = False
    photo_url: str = ""

    @property
    def display_name(self) -> str:
        full = " ".join(p for p in (self.first_name, self.last_name) if p).strip()
        return full or self.username or str(self.id)


@dataclass(frozen=True)
class InitData:
    user: WebAppUser
    auth_date: datetime
    query_id: str = ""
    start_param: str = ""


def _secret_key(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()


def _data_check_string(pairs: list[tuple[str, str]], *, skip: set[str]) -> str:
    return "\n".join(
        f"{k}={v}" for k, v in sorted(pairs, key=itemgetter(0)) if k not in skip
    )


def _expected_hash(pairs: list[tuple[str, str]], *, bot_token: str, skip: set[str]) -> str:
    return hmac.new(
        _secret_key(bot_token),
        _data_check_string(pairs, skip=skip).encode(),
        hashlib.sha256,
    ).hexdigest()


def _parse_user(raw: str) -> WebAppUser:
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise InitDataError("no_user", "user is not valid JSON") from exc
    if not isinstance(data, dict) or not isinstance(data.get("id"), int):
        raise InitDataError("no_user", "user.id missing")
    return WebAppUser(
        id=int(data["id"]),
        first_name=str(data.get("first_name") or ""),
        last_name=str(data.get("last_name") or ""),
        username=str(data.get("username") or ""),
        language_code=str(data.get("language_code") or ""),
        is_premium=bool(data.get("is_premium")),
        photo_url=str(data.get("photo_url") or ""),
    )


def verify_init_data(
    init_data: str,
    *,
    bot_token: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: datetime | None = None,
) -> InitData:
    """Проверить подпись и свежесть initData. Ошибка → InitDataError с кодом.

    ttl_seconds <= 0 отключает проверку свежести (только для тестов/диагностики).
    """
    if not bot_token:
        raise InitDataError("not_configured", "bot token is empty")
    if not init_data:
        raise InitDataError("malformed", "empty init data")

    try:
        pairs = parse_qsl(init_data, strict_parsing=True, keep_blank_values=True)
    except ValueError as exc:
        raise InitDataError("malformed", "not a query string") from exc

    received = [v for k, v in pairs if k == "hash"]
    if len(received) != 1:
        raise InitDataError("no_hash", "hash missing or duplicated")

    # `signature` (Bot API 7.2+) входит в data-check-string: по докам Telegram
    # он подписывает «все поля кроме hash», то есть считается раньше hash.
    # Запасной вариант без него — страховка от расхождения клиентов; на
    # стойкость не влияет, т.к. signature мы не используем.
    variants = [{"hash"}]
    if any(k == "signature" for k, _ in pairs):
        variants.append({"hash", "signature"})
    if not any(
        hmac.compare_digest(_expected_hash(pairs, bot_token=bot_token, skip=skip), received[0])
        for skip in variants
    ):
        raise InitDataError("bad_signature", "hash mismatch")

    fields = dict(pairs)

    raw_auth_date = fields.get("auth_date", "")
    if not raw_auth_date.isdigit():
        raise InitDataError("no_auth_date", "auth_date missing")
    auth_date = datetime.fromtimestamp(int(raw_auth_date), tz=UTC)
    if ttl_seconds > 0:
        moment = now or datetime.now(UTC)
        if (moment - auth_date).total_seconds() > ttl_seconds:
            raise InitDataError("expired", "init data is too old")

    if "user" not in fields:
        raise InitDataError("no_user", "user missing")

    return InitData(
        user=_parse_user(fields["user"]),
        auth_date=auth_date,
        query_id=fields.get("query_id", ""),
        start_param=fields.get("start_param", ""),
    )


def build_init_data(payload: dict[str, str], *, bot_token: str) -> str:
    """Собрать подписанный initData. Только для тестов и локальной отладки."""
    pairs = sorted(payload.items(), key=itemgetter(0))
    digest = _expected_hash(list(pairs), bot_token=bot_token, skip=set())
    return urlencode([*pairs, ("hash", digest)])
