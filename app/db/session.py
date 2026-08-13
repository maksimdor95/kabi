"""Async engine и фабрика сессий. Спека: docs/services/persistence.md"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings


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
    """Привести схему к Alembic head (M10). Без create_all / ручных ALTER."""
    from app.db.migrate import ensure_schema

    await ensure_schema(engine)
