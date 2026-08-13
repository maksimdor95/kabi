"""Программный запуск Alembic (stamp существующих БД + upgrade).

Спека: docs/services/persistence.md (M10)
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.observability.logging import get_logger

logger = get_logger("kabi.db.migrate")

_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _ROOT / "alembic.ini"
BASELINE_REVISION = "20260813_0001"


def _alembic_config() -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_ROOT / "alembic"))
    return cfg


def upgrade_head() -> None:
    """Синхронный alembic upgrade head (для CLI и init_db)."""
    command.upgrade(_alembic_config(), "head")


def stamp_head() -> None:
    command.stamp(_alembic_config(), "head")


async def _table_exists(engine: AsyncEngine, name: str) -> bool:
    async with engine.connect() as conn:
        row = await conn.execute(
            text("SELECT to_regclass(:name) IS NOT NULL"),
            {"name": f"public.{name}"},
        )
        return bool(row.scalar())


async def ensure_schema(engine: AsyncEngine) -> None:
    """Идемпотентно привести схему к head.

    - Всегда: CREATE EXTENSION vector
    - Если таблицы уже есть (старый create_all), а alembic_version нет → stamp head
    - Иначе → upgrade head (пустая БД создаст схему; stamped — no-op)

    Alembic дергаем через to_thread: его env.py сам делает asyncio.run,
    нельзя вызывать из уже запущенного event loop бота.
    """
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    has_users = await _table_exists(engine, "users")
    has_version = await _table_exists(engine, "alembic_version")

    if has_users and not has_version:
        logger.info(
            "existing schema without alembic_version → stamp %s",
            BASELINE_REVISION,
        )
        await asyncio.to_thread(stamp_head)
        return

    logger.info("alembic upgrade head")
    await asyncio.to_thread(upgrade_head)
