"""Async engine и фабрика сессий. Спека: docs/services/persistence.md"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.db.models import Base


def _database_url() -> str:
    return (
        f"postgresql+asyncpg://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


engine = create_async_engine(_database_url(), pool_pre_ping=True)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session


async def init_db() -> None:
    """Создать расширение pgvector и таблицы. Для MVP; позже — Alembic."""
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        # create_all не добавляет колонки в существующие таблицы — доклеиваем вручную.
        await conn.execute(
            text("ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS meta JSONB")
        )
        await conn.execute(
            text("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS digest_schedule JSONB")
        )
        await conn.execute(
            text("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS last_digest_at JSONB")
        )
