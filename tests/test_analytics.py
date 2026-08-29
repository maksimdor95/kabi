"""P1 product analytics: emit + deliver_feed."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import analytics
from app.services import digest as digest_service
from app.services.digest import DigestItem


@pytest.mark.asyncio
async def test_emit_adds_product_event():
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    pid = uuid.uuid4()

    await analytics.emit(
        session,
        name="empty_state",
        profile_id=pid,
        props={"scope": "jobs", "channel": "bot"},
    )

    session.add.assert_called_once()
    event = session.add.call_args[0][0]
    assert event.profile_id == pid
    assert event.name == "empty_state"
    assert event.props == {"scope": "jobs", "channel": "bot"}
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_emit_swallows_flush_errors():
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock(side_effect=RuntimeError("db down"))

    await analytics.emit(
        session,
        name="cv_uploaded",
        profile_id=uuid.uuid4(),
        props={"roles_n": 1, "skills_n": 2},
    )
    # не пробрасываем


@pytest.mark.asyncio
async def test_emit_skips_unknown_event():
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    await analytics.emit(
        session,
        name="not_a_real_event",
        profile_id=uuid.uuid4(),
    )
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_deliver_feed_empty_emits_empty_state():
    session = MagicMock()
    profile = SimpleNamespace(id=uuid.uuid4())
    emits: list[dict] = []

    async def fake_emit(session, *, name, profile_id, props=None):
        emits.append({"name": name, "profile_id": profile_id, "props": props})

    with (
        patch("app.services.analytics.emit", new=fake_emit),
        patch.object(digest_service, "mark_shown", new_callable=AsyncMock) as shown,
    ):
        out = await digest_service.deliver_feed(
            session, profile, [], scope="pitch", channel="miniapp"
        )

    assert out == []
    shown.assert_not_awaited()
    assert len(emits) == 1
    assert emits[0]["name"] == "empty_state"
    assert emits[0]["props"] == {"scope": "pitch", "channel": "miniapp"}


@pytest.mark.asyncio
async def test_deliver_feed_items_marks_shown_and_emits():
    session = MagicMock()
    profile = SimpleNamespace(id=uuid.uuid4())
    mid = str(uuid.uuid4())
    item = DigestItem(
        match_id=mid,
        score=0.9,
        reason="fit",
        title="PM",
        org="Acme",
        location=None,
        remote=True,
        salary=None,
        url=None,
        source=None,
    )
    emits: list[dict] = []

    async def fake_emit(session, *, name, profile_id, props=None):
        emits.append({"name": name, "props": props})

    with (
        patch("app.services.analytics.emit", new=fake_emit),
        patch.object(digest_service, "mark_shown", new_callable=AsyncMock) as shown,
    ):
        out = await digest_service.deliver_feed(
            session, profile, [item], scope="jobs", channel="bot"
        )

    assert out == [item]
    shown.assert_awaited_once_with(session, [mid])
    assert emits[0]["name"] == "digest_shown"
    assert emits[0]["props"]["n"] == 1
    assert emits[0]["props"]["match_ids"] == [mid]
    assert emits[0]["props"]["channel"] == "bot"


@pytest.mark.asyncio
async def test_record_reaction_emits_card_reacted():
    from app.services import feedback as feedback_service

    mid = uuid.uuid4()
    pid = uuid.uuid4()
    match = SimpleNamespace(
        id=mid, status="new", profile_id=pid, opportunity_id=uuid.uuid4()
    )
    session = MagicMock()
    session.get = AsyncMock(return_value=match)
    session.add = MagicMock()
    session.flush = AsyncMock()
    emits: list[dict] = []

    async def fake_emit(session, *, name, profile_id, props=None):
        emits.append({"name": name, "profile_id": profile_id, "props": props})

    with patch("app.services.analytics.emit", new=fake_emit):
        r = await feedback_service.record_reaction(session, str(mid), "hide")

    assert r.ok and r.effect == "hide"
    assert emits[0]["name"] == "card_reacted"
    assert emits[0]["profile_id"] == pid
    assert emits[0]["props"]["reaction"] == "hide"


@pytest.mark.asyncio
async def test_draft_for_match_emits_draft_generated():
    from app.services import drafts as drafts_service

    mid = uuid.uuid4()
    pid = uuid.uuid4()
    profile = SimpleNamespace(id=pid)
    match = SimpleNamespace(id=mid, profile_id=pid, opportunity_id=uuid.uuid4())
    opp = SimpleNamespace(type="job", title="X", org=None, description=None)

    session = MagicMock()
    session.execute = AsyncMock(
        return_value=MagicMock(first=MagicMock(return_value=(match, opp)))
    )
    emits: list[dict] = []

    async def fake_emit(session, *, name, profile_id, props=None):
        emits.append({"name": name, "props": props})

    with (
        patch("app.services.analytics.emit", new=fake_emit),
        patch.object(
            drafts_service,
            "draft_for_opportunity",
            new=AsyncMock(return_value="draft text"),
        ),
    ):
        r = await drafts_service.draft_for_match(session, profile, str(mid))

    assert r.ok and r.kind == "cover_letter"
    assert emits[0]["name"] == "draft_generated"
    assert emits[0]["props"]["kind"] == "cover_letter"
