"""Acceptance A1–A7 из docs/services/miniapp.md §9: подпись initData."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import pytest

from app.api.auth import InitDataError, build_init_data, verify_init_data

TOKEN = "123456:AAHtest-bot-token-for-unit-tests"
OTHER_TOKEN = "999999:BBHsomebody-elses-bot-token"

USER = {
    "id": 42,
    "first_name": "Мария",
    "last_name": "Дорошенко",
    "username": "maria",
    "language_code": "ru",
    "is_premium": True,
}


def _payload(*, auth_date: datetime | None = None, **extra: str) -> dict[str, str]:
    moment = auth_date or datetime.now(UTC)
    return {
        "auth_date": str(int(moment.timestamp())),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": json.dumps(USER, ensure_ascii=False, separators=(",", ":")),
        **extra,
    }


def test_a1_valid_init_data_resolves_user():
    raw = build_init_data(_payload(), bot_token=TOKEN)

    data = verify_init_data(raw, bot_token=TOKEN)

    assert data.user.id == 42
    assert data.user.username == "maria"
    assert data.user.display_name == "Мария Дорошенко"
    assert data.query_id == "AAHdF6IQAAAAAN0XohDhrOrc"


def test_a2_tampered_field_rejected():
    payload = _payload()
    raw = build_init_data(payload, bot_token=TOKEN)
    forged_user = json.dumps({**USER, "id": 777}, ensure_ascii=False, separators=(",", ":"))
    tampered = raw.replace(urlencode({"user": payload["user"]}), urlencode({"user": forged_user}))
    assert tampered != raw

    with pytest.raises(InitDataError) as exc:
        verify_init_data(tampered, bot_token=TOKEN)
    assert exc.value.code == "bad_signature"


def test_a3_expired_init_data_rejected():
    stale = datetime.now(UTC) - timedelta(hours=30)
    raw = build_init_data(_payload(auth_date=stale), bot_token=TOKEN)

    with pytest.raises(InitDataError) as exc:
        verify_init_data(raw, bot_token=TOKEN, ttl_seconds=24 * 3600)
    assert exc.value.code == "expired"

    # без TTL та же строка валидна — протухание не влияет на подпись
    assert verify_init_data(raw, bot_token=TOKEN, ttl_seconds=0).user.id == 42


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("", "malformed"),
        ("not-a-query-string", "malformed"),
        ("auth_date=1&user=%7B%7D", "no_hash"),
    ],
)
def test_a4_malformed_init_data(raw: str, code: str):
    with pytest.raises(InitDataError) as exc:
        verify_init_data(raw, bot_token=TOKEN)
    assert exc.value.code == code


def test_a5_foreign_bot_token_rejected():
    raw = build_init_data(_payload(), bot_token=OTHER_TOKEN)

    with pytest.raises(InitDataError) as exc:
        verify_init_data(raw, bot_token=TOKEN)
    assert exc.value.code == "bad_signature"


def test_a6_signature_field_is_part_of_hash():
    """Bot API 7.2+ шлёт `signature`; он входит в data-check-string."""
    raw = build_init_data(_payload(signature="Zm9vYmFy"), bot_token=TOKEN)

    assert "signature=" in raw
    assert verify_init_data(raw, bot_token=TOKEN).user.id == 42


def test_a6b_hash_computed_without_signature_still_accepted():
    """Страховка на случай клиента, который считает hash без `signature`."""
    payload = _payload()
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    check = "\n".join(f"{k}={v}" for k, v in sorted(payload.items()))
    digest = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    raw = urlencode([*sorted(payload.items()), ("signature", "Zm9vYmFy"), ("hash", digest)])

    assert verify_init_data(raw, bot_token=TOKEN).user.id == 42


def test_a7_missing_user_rejected():
    payload = {"auth_date": str(int(datetime.now(UTC).timestamp()))}
    raw = build_init_data(payload, bot_token=TOKEN)

    with pytest.raises(InitDataError) as exc:
        verify_init_data(raw, bot_token=TOKEN)
    assert exc.value.code == "no_user"


def test_empty_bot_token_is_configuration_error():
    raw = build_init_data(_payload(), bot_token=TOKEN)

    with pytest.raises(InitDataError) as exc:
        verify_init_data(raw, bot_token="")
    assert exc.value.code == "not_configured"


def test_auth_date_must_be_present():
    raw = build_init_data(
        {"user": json.dumps(USER, ensure_ascii=False, separators=(",", ":"))},
        bot_token=TOKEN,
    )

    with pytest.raises(InitDataError) as exc:
        verify_init_data(raw, bot_token=TOKEN)
    assert exc.value.code == "no_auth_date"
