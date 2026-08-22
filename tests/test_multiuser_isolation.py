"""MU-A: изоляция профилей (docs/services/multiuser.md)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import dialog_memory
from app.services import feedback as feedback_service
from app.services import profile as profile_service


@pytest.mark.asyncio
async def test_i3_foreign_match_reaction_forbidden():
    """Чужой match_id не меняет статус и не пишет Feedback."""
    mid = uuid.uuid4()
    owner_pid = uuid.uuid4()
    actor_pid = uuid.uuid4()
    match = SimpleNamespace(
        id=mid,
        status="new",
        profile_id=owner_pid,
        opportunity_id=uuid.uuid4(),
    )
    session = MagicMock()
    session.get = AsyncMock(return_value=match)
    session.add = MagicMock()
    session.flush = AsyncMock()

    result = await feedback_service.record_reaction(
        session,
        str(mid),
        "up",
        actor_profile_id=actor_pid,
    )
    assert result.ok is False
    assert result.effect == "forbidden"
    assert match.status == "new"
    session.add.assert_not_called()
    session.flush.assert_not_called()


@pytest.mark.asyncio
async def test_i3_owner_reaction_allowed():
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    match = SimpleNamespace(
        id=mid,
        status="new",
        profile_id=pid,
        opportunity_id=uuid.uuid4(),
    )
    session = MagicMock()
    session.get = AsyncMock(return_value=match)
    session.add = MagicMock()
    session.flush = AsyncMock()

    result = await feedback_service.record_reaction(
        session,
        str(mid),
        "save",
        actor_profile_id=pid,
    )
    assert result.ok is True
    assert result.effect == "saved"
    assert match.status == "saved"


@pytest.mark.asyncio
async def test_i2_list_saved_scoped_by_profile_id():
    """list_saved фильтрует по profile.id (контракт запроса)."""
    import inspect

    from app.services import feedback as fb

    src = inspect.getsource(fb.list_saved)
    assert "Match.profile_id == profile.id" in src


@pytest.mark.asyncio
async def test_i6_dialog_memory_keys_differ_per_user():
    dialog_memory.reset_for_tests()
    dialog_memory._redis_failed = True
    u1, u2 = uuid.uuid4(), uuid.uuid4()
    await dialog_memory.append_turn(u1, "привет от A", "ответ A")
    await dialog_memory.append_turn(u2, "привет от B", "ответ B")
    h1 = await dialog_memory.get_history(u1)
    h2 = await dialog_memory.get_history(u2)
    assert h1[0]["content"] == "привет от A"
    assert h2[0]["content"] == "привет от B"
    assert h1 != h2
    dialog_memory.reset_for_tests()


@pytest.mark.asyncio
async def test_i4_delete_uses_telegram_id_not_all_profiles():
    """delete_account ищет User по telegram_id (не wipe всей базы)."""
    import inspect

    src = inspect.getsource(profile_service.delete_account)
    assert "User.telegram_id == telegram_id" in src
    assert "dialog_memory.clear" in src


@pytest.mark.asyncio
async def test_i5_scheduler_joins_user_telegram_id():
    import inspect

    from app.scheduler import jobs

    src = inspect.getsource(jobs.scheduled_digests)
    assert "User.telegram_id" in src
    assert "Profile.user_id" in src or "User.id == Profile.user_id" in src


def test_multiuser_spec_exists():
    from pathlib import Path

    text = Path("docs/services/multiuser.md").read_text(encoding="utf-8")
    assert "actor.profile.id" in text or "actor_profile" in text or "match.profile_id" in text
    assert "Opportunity" in text and "общий" in text.lower()
