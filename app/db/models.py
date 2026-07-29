"""ORM-модели (SQLAlchemy 2.0). См. docs/architecture/data-model.md

Векторные поля — 256-мерные (Yandex text-search-*).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.llm.client import EMBED_DIM


class Base(DeclarativeBase):
    pass


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    profile: Mapped["Profile"] = relationship(back_populates="user", uselist=False)


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True)

    # PARSE (из CV)
    skills: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    experience: Mapped[list | None] = mapped_column(JSONB, default=list)
    roles: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    languages: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    work_mode: Mapped[str | None] = mapped_column(String, nullable=True)

    # ASK (онбординг)
    salary_expectation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    priorities: Mapped[str] = mapped_column(String, default="both")
    job_search_status: Mapped[str] = mapped_column(String, default="passive")
    hard_nos: Mapped[dict] = mapped_column(JSONB, default=dict)
    availability: Mapped[dict] = mapped_column(JSONB, default=dict)
    goals: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ENRICH
    speaking_topics: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    enrichment_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    source_links: Mapped[dict] = mapped_column(JSONB, default=dict)

    raw_cv_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM), nullable=True)
    ready_for_matching: Mapped[bool] = mapped_column(Boolean, default=False)
    onboarding_step: Mapped[int] = mapped_column(default=0)
    # Расписание рассылок: {timezone, jobs: {enabled,days,hour,minute}, talks: {...}}
    digest_schedule: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Идемпотентность: {"jobs": "2026-07-26", "talks": "2026-07-23"}
    last_digest_at: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="profile")


class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    type: Mapped[str] = mapped_column(String, index=True)  # job | talk
    title: Mapped[str] = mapped_column(String)
    org: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    remote: Mapped[bool] = mapped_column(Boolean, default=False)
    salary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    external_id: Mapped[str | None] = mapped_column(String, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id"), index=True)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("opportunities.id"))
    score: Mapped[float] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, default="new", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    match_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("matches.id"))
    reaction: Mapped[str] = mapped_column(String)  # up | down | hide | save
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DeadlineReminderLog(Base):
    """Идемпотентность напоминаний о дедлайнах (profile + opportunity + окно)."""

    __tablename__ = "deadline_reminder_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id"), index=True)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("opportunities.id"), index=True)
    window_days: Mapped[int] = mapped_column()  # 14 | 7 | 3 | 1
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
