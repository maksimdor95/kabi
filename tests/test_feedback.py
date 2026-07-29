"""Тесты реакций feedback (save / unsave / embedding blend)."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import feedback as feedback_service
from app.services.feedback import blend_embedding, cosine_similarity


def test_blend_up_increases_similarity():
    base = [1.0, 0.0, 0.0]
    delta = [0.0, 1.0, 0.0]
    before = cosine_similarity(base, delta)
    after_vec = blend_embedding(base, delta, sign=1, alpha=0.15)
    after = cosine_similarity(after_vec, delta)
    assert after > before


def test_blend_down_decreases_similarity():
    # base уже слегка в сторону delta
    base = blend_embedding([1.0, 0.0, 0.0], [0.0, 1.0, 0.0], sign=1, alpha=0.5)
    delta = [0.0, 1.0, 0.0]
    before = cosine_similarity(base, delta)
    after_vec = blend_embedding(base, delta, sign=-1, alpha=0.20)
    after = cosine_similarity(after_vec, delta)
    assert after < before


@pytest.mark.asyncio
async def test_save_then_toggle_unsave():
    mid = uuid.uuid4()
    match = SimpleNamespace(id=mid, status="new", profile_id=uuid.uuid4(), opportunity_id=uuid.uuid4())
    session = MagicMock()
    session.get = AsyncMock(return_value=match)
    session.add = MagicMock()
    session.flush = AsyncMock()

    r1 = await feedback_service.record_reaction(session, str(mid), "save")
    assert r1.ok and r1.effect == "saved"
    assert match.status == "saved"
    assert r1.learned is False

    r2 = await feedback_service.record_reaction(session, str(mid), "save")
    assert r2.ok and r2.effect == "unsaved"
    assert match.status == "new"

    await feedback_service.record_reaction(session, str(mid), "save")
    r3 = await feedback_service.record_reaction(session, str(mid), "unsave")
    assert r3.ok and r3.effect == "unsaved"
    assert match.status == "new"


@pytest.mark.asyncio
async def test_up_blends_profile_embedding():
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    oid = uuid.uuid4()
    match = SimpleNamespace(
        id=mid, status="new", profile_id=pid, opportunity_id=oid
    )
    profile = SimpleNamespace(id=pid, embedding=[1.0, 0.0, 0.0])
    opp = SimpleNamespace(id=oid, embedding=[0.0, 1.0, 0.0])

    async def fake_get(model, key):
        if key == mid:
            return match
        if key == pid:
            return profile
        if key == oid:
            return opp
        return None

    session = MagicMock()
    session.get = AsyncMock(side_effect=fake_get)
    session.add = MagicMock()
    session.flush = AsyncMock()

    before = cosine_similarity(profile.embedding, opp.embedding)
    r = await feedback_service.record_reaction(session, str(mid), "up")
    assert r.ok and r.effect == "up" and r.learned is True
    assert match.status == "liked"
    after = cosine_similarity(list(profile.embedding), opp.embedding)
    assert after > before
