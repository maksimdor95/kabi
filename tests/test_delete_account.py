"""Тесты удаления аккаунта (docs/services/profile.md → delete_account)."""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import profile as profile_service


@pytest.mark.asyncio
async def test_delete_account_missing_user():
    session = MagicMock()
    session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    result = await profile_service.delete_account(session, 42)
    assert result.deleted is False
    assert result.had_profile is False
    session.delete.assert_not_called()


@pytest.mark.asyncio
async def test_delete_account_cascades():
    uploads = Path("uploads")
    uploads.mkdir(exist_ok=True)
    cv_path = uploads / f"del_test_{uuid.uuid4().hex}.pdf"
    cv_path.write_bytes(b"%PDF")

    user = SimpleNamespace(id=uuid.uuid4(), telegram_id=123)
    profile = SimpleNamespace(id=uuid.uuid4(), user_id=user.id, raw_cv_ref=str(cv_path))
    mid = uuid.uuid4()

    async def execute(stmt):
        s = str(stmt).lower()
        if "users" in s:
            return MagicMock(scalar_one_or_none=MagicMock(return_value=user))
        if "matches" in s and "select" in s:
            return MagicMock(
                scalars=MagicMock(
                    return_value=MagicMock(all=MagicMock(return_value=[mid]))
                )
            )
        return MagicMock()

    session = MagicMock()
    session.execute = AsyncMock(side_effect=execute)
    session.delete = AsyncMock()
    session.flush = AsyncMock()

    with patch.object(profile_service, "get_profile", AsyncMock(return_value=profile)):
        result = await profile_service.delete_account(session, 123)

    assert result.deleted is True
    assert result.had_profile is True
    assert result.matches_removed == 1
    assert result.cv_file_removed is True
    assert not cv_path.exists()
    session.delete.assert_any_call(profile)
    session.delete.assert_any_call(user)
    session.flush.assert_awaited()


@pytest.mark.asyncio
async def test_delete_account_user_without_profile():
    user = SimpleNamespace(id=uuid.uuid4(), telegram_id=7)
    session = MagicMock()
    session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=user))
    )
    session.delete = AsyncMock()
    session.flush = AsyncMock()

    with patch.object(profile_service, "get_profile", AsyncMock(return_value=None)):
        result = await profile_service.delete_account(session, 7)

    assert result.deleted is True
    assert result.had_profile is False
    session.delete.assert_called_once_with(user)


def test_unlink_cv_rejects_outside_uploads(tmp_path):
    outsider = tmp_path / "secret.pdf"
    outsider.write_bytes(b"x")
    assert profile_service._unlink_cv_if_local(str(outsider)) is False
    assert outsider.exists()


def test_unlink_cv_ok_inside_uploads():
    uploads = Path("uploads")
    uploads.mkdir(exist_ok=True)
    path = uploads / f"ok_{uuid.uuid4().hex}.pdf"
    path.write_bytes(b"x")
    assert profile_service._unlink_cv_if_local(str(path)) is True
    assert not path.exists()
