"""Acceptance M1–M5 из docs/services/miniapp.md §9: контракт HTTP-ручек.

БД и LLM подменяем: проверяем транспорт, авторизацию и изоляцию (MU-A),
а не то, что уже покрыто тестами сервисов.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.api.auth import build_init_data
from app.api.deps import db_session, expensive_limiter
from app.config import settings
from app.main import app
from app.services.digest import DigestItem
from app.services.drafts import DraftResult
from app.services.feedback import ReactionResult

TOKEN = "123456:AAHtest-bot-token-for-unit-tests"
TG_ID = 42


def _init_data(*, tg_id: int = TG_ID) -> str:
    user = json.dumps({"id": tg_id, "first_name": "Мария"}, ensure_ascii=False)
    return build_init_data(
        {"auth_date": str(int(datetime.now(UTC).timestamp())), "user": user},
        bot_token=TOKEN,
    )


def _auth(tg_id: int = TG_ID) -> dict[str, str]:
    return {"Authorization": f"tma {_init_data(tg_id=tg_id)}"}


def _profile(*, ready: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        roles=["Product Manager"],
        skills=["discovery", "аналитика"],
        location="Москва",
        work_mode="гибрид",
        languages=["ru", "en"],
        speaking_topics=["продуктовая аналитика"],
        goals="вырасти до head of product",
        salary_expectation={"min": 400000, "currency": "RUB"},
        priorities="both",
        hard_nos={"raw": "без релокации"},
        source_links={"links": ["https://example.com"]},
        ready_for_matching=ready,
        onboarding_step=99 if ready else 2,
        updated_at=datetime.now(UTC),
    )


def _item(*, title: str = "Product Manager") -> DigestItem:
    return DigestItem(
        match_id=str(uuid.uuid4()),
        score=0.81,
        reason="Совпали продуктовая аналитика и опыт запуска маркетплейсов на данных.",
        title=title,
        org="Ozon",
        location="Москва",
        remote=True,
        salary={"min": 400000, "currency": "RUB"},
        url="https://example.com/vacancy/1",
        source="hh.ru",
    )


class FakeSession:
    """Минимум, который нужен ручкам: скалярный COUNT и no-op транзакции."""

    def __init__(self, scalar: int = 0) -> None:
        self.scalar = scalar

    async def execute(self, *_args, **_kwargs):
        return SimpleNamespace(scalar_one=lambda: self.scalar)

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


@pytest.fixture
def api(monkeypatch):
    """Клиент с валидным токеном бота и подменённым доступом к БД."""
    monkeypatch.setattr(settings, "telegram_bot_token", TOKEN)
    monkeypatch.setattr(settings, "miniapp_auth_ttl_seconds", 86400)
    expensive_limiter._hits.clear()

    state = SimpleNamespace(profile=_profile(), session=FakeSession())

    async def fake_get_or_create_user(_session, telegram_id: int):
        return SimpleNamespace(id=uuid.uuid4(), telegram_id=telegram_id)

    async def fake_get_profile(_session, _user_id):
        return state.profile

    monkeypatch.setattr(deps.profile_service, "get_or_create_user", fake_get_or_create_user)
    monkeypatch.setattr(deps.profile_service, "get_profile", fake_get_profile)

    async def override_session():
        yield state.session

    app.dependency_overrides[db_session] = override_session
    with TestClient(app) as client:
        yield client, state
    app.dependency_overrides.clear()


# --------------------------- авторизация ---------------------------


def test_health_needs_no_auth(api):
    client, _ = api
    assert client.get("/health").json() == {"status": "ok"}


def test_missing_authorization_header_is_401(api):
    client, _ = api
    response = client.get("/api/v1/feed")
    assert response.status_code == 401
    assert response.json()["code"] == "malformed"


def test_foreign_signature_is_401(api):
    client, _ = api
    forged = build_init_data(
        {
            "auth_date": str(int(datetime.now(UTC).timestamp())),
            "user": json.dumps({"id": 777, "first_name": "Мимо"}),
        },
        bot_token="999999:someone-elses-token",
    )
    response = client.get("/api/v1/feed", headers={"Authorization": f"tma {forged}"})
    assert response.status_code == 401
    assert response.json()["code"] == "bad_signature"


def test_config_is_public(api):
    client, _ = api
    body = client.get("/api/v1/config").json()
    assert body["scopes"] == ["jobs", "pitch", "talks"]


# --------------------------- профиль ---------------------------


def test_m4_no_profile_is_404(api, monkeypatch):
    client, _ = api

    async def no_profile(_session, _user_id):
        return None

    monkeypatch.setattr(deps.profile_service, "get_profile", no_profile)
    response = client.get("/api/v1/me", headers=_auth())
    assert response.status_code == 404
    assert response.json()["code"] == "no_profile"


def test_me_returns_profile_summary(api):
    client, state = api
    state.session.scalar = 3

    body = client.get("/api/v1/me", headers=_auth()).json()

    assert body["telegram_id"] == TG_ID
    assert body["display_name"] == "Мария"
    assert body["roles"] == ["Product Manager"]
    assert body["salary_min"] == 400000
    assert body["saved_count"] == 3
    assert body["ready_for_matching"] is True
    assert body["onboarding_question"] is None


# --------------------------- подборка ---------------------------


def test_m1_feed_lists_pending_without_ingest(api, monkeypatch):
    client, _ = api
    seen_pending: dict[str, object] = {}
    build_calls = {"n": 0}

    async def fake_build(*_a, **_k):
        build_calls["n"] += 1
        raise AssertionError("GET /feed не должен звать build_digest")

    async def fake_pending(_session, _profile, **kwargs):
        seen_pending.update(kwargs)
        return [_item()]

    monkeypatch.setattr("app.api.routes.digest_service.build_digest", fake_build)
    monkeypatch.setattr("app.api.routes.digest_service.list_pending", fake_pending)

    body = client.get("/api/v1/feed?scope=jobs", headers=_auth()).json()

    assert build_calls["n"] == 0
    assert seen_pending["scope"] == "jobs"
    assert body["refreshed"] is False
    card = body["items"][0]
    assert card["title"] == "Product Manager"
    assert card["salary"] == "от 400 000 RUB"
    assert card["source"] == "HeadHunter"


def test_refresh_feed_ingests_then_lists_pending(api, monkeypatch):
    client, _ = api
    seen_build: dict[str, object] = {}
    seen_pending: dict[str, object] = {}

    async def fake_build(_session, _profile, **kwargs):
        seen_build.update(kwargs)
        return []

    async def fake_pending(_session, _profile, **kwargs):
        seen_pending.update(kwargs)
        return [_item(title="После refresh")]

    monkeypatch.setattr("app.api.routes.digest_service.build_digest", fake_build)
    monkeypatch.setattr("app.api.routes.digest_service.list_pending", fake_pending)

    body = client.post("/api/v1/feed/refresh?scope=talks", headers=_auth()).json()

    assert seen_build["do_ingest"] is True
    assert seen_build["scope"] == "talks"
    assert seen_pending["scope"] == "talks"
    assert body["refreshed"] is True
    assert body["items"][0]["title"] == "После refresh"


def test_m5_not_ready_profile_gets_409(api, monkeypatch):
    client, state = api
    state.profile = _profile(ready=False)

    async def fail(*_args, **_kwargs):  # pragma: no cover
        raise AssertionError("не должен вызываться для неготового профиля")

    monkeypatch.setattr("app.api.routes.digest_service.build_digest", fail)
    monkeypatch.setattr("app.api.routes.digest_service.list_pending", fail)

    response = client.get("/api/v1/feed", headers=_auth())
    assert response.status_code == 409
    assert response.json()["code"] == "profile_not_ready"


def test_bad_scope_is_422(api):
    client, _ = api
    assert client.get("/api/v1/feed?scope=hacking", headers=_auth()).status_code == 422


# --------------------------- избранное и реакции ---------------------------


def test_m3_saved_is_scoped_to_own_profile(api, monkeypatch):
    client, state = api
    seen: dict[str, object] = {}

    async def fake_saved(_session, profile):
        seen["profile_id"] = profile.id
        return [_item(title="Head of Product")]

    monkeypatch.setattr("app.api.routes.feedback_service.list_saved", fake_saved)

    body = client.get("/api/v1/saved", headers=_auth()).json()

    assert seen["profile_id"] == state.profile.id
    assert body[0]["saved"] is True
    assert body[0]["title"] == "Head of Product"


def test_reaction_passes_actor_profile(api, monkeypatch):
    client, state = api
    seen: dict[str, object] = {}

    async def fake_reaction(_session, match_id, reaction, *, actor_profile_id=None):
        seen.update(match_id=match_id, reaction=reaction, actor=actor_profile_id)
        return ReactionResult(ok=True, effect="saved", learned=False)

    monkeypatch.setattr("app.api.routes.feedback_service.record_reaction", fake_reaction)

    match_id = str(uuid.uuid4())
    body = client.post(
        f"/api/v1/matches/{match_id}/reaction",
        headers=_auth(),
        json={"reaction": "save"},
    ).json()

    assert seen["actor"] == state.profile.id
    assert seen["match_id"] == match_id
    assert body == {"ok": True, "effect": "saved", "learned": False}


def test_m2_reaction_on_foreign_match_is_403(api, monkeypatch):
    client, _ = api

    async def fake_reaction(*_args, **_kwargs):
        return ReactionResult(ok=False, effect="forbidden")

    monkeypatch.setattr("app.api.routes.feedback_service.record_reaction", fake_reaction)

    response = client.post(
        f"/api/v1/matches/{uuid.uuid4()}/reaction",
        headers=_auth(),
        json={"reaction": "up"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_unknown_reaction_is_422(api):
    client, _ = api
    response = client.post(
        f"/api/v1/matches/{uuid.uuid4()}/reaction",
        headers=_auth(),
        json={"reaction": "explode"},
    )
    assert response.status_code == 422


# --------------------------- черновики и лимиты ---------------------------


def test_draft_returns_text(api, monkeypatch):
    client, _ = api

    async def fake_draft(_session, _profile, _match_id):
        return DraftResult(ok=True, kind="talk_pitch", text="Здравствуйте, предлагаю тему…")

    monkeypatch.setattr("app.api.routes.drafts_service.draft_for_match", fake_draft)

    body = client.post(f"/api/v1/matches/{uuid.uuid4()}/draft", headers=_auth()).json()
    assert body["kind"] == "talk_pitch"
    assert body["text"].startswith("Здравствуйте")


def test_draft_on_foreign_match_is_403(api, monkeypatch):
    client, _ = api

    async def fake_draft(*_args):
        return DraftResult(ok=False, error="forbidden")

    monkeypatch.setattr("app.api.routes.drafts_service.draft_for_match", fake_draft)

    response = client.post(f"/api/v1/matches/{uuid.uuid4()}/draft", headers=_auth())
    assert response.status_code == 403


def test_expensive_endpoints_are_rate_limited(api, monkeypatch):
    client, _ = api

    async def fake_draft(*_args):
        return DraftResult(ok=True, kind="cover_letter", text="ок")

    monkeypatch.setattr("app.api.routes.drafts_service.draft_for_match", fake_draft)

    codes = [
        client.post(f"/api/v1/matches/{uuid.uuid4()}/draft", headers=_auth()).status_code
        for _ in range(expensive_limiter.limit + 1)
    ]
    assert codes[:-1] == [200] * expensive_limiter.limit
    assert codes[-1] == 429


def test_api_responses_are_not_cached(api, monkeypatch):
    client, _ = api

    async def fake_saved(*_args):
        return []

    monkeypatch.setattr("app.api.routes.feedback_service.list_saved", fake_saved)

    response = client.get("/api/v1/saved", headers=_auth())
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors" in response.headers["content-security-policy"]
