"""Тесты M10: baseline revision и логика stamp/upgrade."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db import migrate as migrate_mod


def test_baseline_revision_file_exists():
    path = Path("alembic/versions/20260813_0001_baseline.py")
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert 'revision: str = "20260813_0001"' in text
    assert "CREATE EXTENSION IF NOT EXISTS vector" in text
    assert "digest_schedule" in text
    assert "last_digest_at" in text
    assert '"meta"' in text or "meta" in text


def test_init_db_no_longer_has_create_all():
    src = Path("app/db/session.py").read_text(encoding="utf-8")
    assert "Base.metadata.create_all" not in src
    assert "ALTER TABLE" not in src
    assert "ensure_schema" in src


@pytest.mark.asyncio
async def test_ensure_schema_stamps_existing_without_version():
    engine = MagicMock()
    with (
        patch.object(migrate_mod, "_table_exists", new_callable=AsyncMock) as exists,
        patch.object(migrate_mod, "stamp_head") as stamp,
        patch.object(migrate_mod, "upgrade_head") as upgrade,
    ):
        # users=True, alembic_version=False
        exists.side_effect = [True, False]
        begin = MagicMock()
        conn = AsyncMock()
        begin.__aenter__ = AsyncMock(return_value=conn)
        begin.__aexit__ = AsyncMock(return_value=None)
        engine.begin.return_value = begin

        await migrate_mod.ensure_schema(engine)
        stamp.assert_called_once()
        upgrade.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_schema_upgrades_when_fresh_or_versioned():
    engine = MagicMock()
    with (
        patch.object(migrate_mod, "_table_exists", new_callable=AsyncMock) as exists,
        patch.object(migrate_mod, "stamp_head") as stamp,
        patch.object(migrate_mod, "upgrade_head") as upgrade,
    ):
        exists.side_effect = [False, False]  # no users → upgrade
        begin = MagicMock()
        conn = AsyncMock()
        begin.__aenter__ = AsyncMock(return_value=conn)
        begin.__aexit__ = AsyncMock(return_value=None)
        engine.begin.return_value = begin

        await migrate_mod.ensure_schema(engine)
        upgrade.assert_called_once()
        stamp.assert_not_called()
