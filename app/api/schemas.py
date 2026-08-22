"""DTO ответов Mini App. Спека: docs/services/miniapp.md §4.

Отдельный слой от ORM: наружу отдаём ровно то, что нужно UI.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Scope = Literal["jobs", "pitch", "talks"]
Reaction = Literal["up", "down", "save", "unsave", "hide"]


class ConfigOut(BaseModel):
    """Публичный конфиг для фронта (без auth, без секретов)."""

    app_env: str
    scopes: list[Scope]


class MeOut(BaseModel):
    telegram_id: int
    display_name: str
    roles: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    location: str | None = None
    work_mode: str | None = None
    languages: list[str] = Field(default_factory=list)
    speaking_topics: list[str] = Field(default_factory=list)
    goals: str | None = None
    salary_min: int | None = None
    salary_currency: str | None = None
    priorities: str = "both"
    hard_nos: str | None = None
    source_links: list[str] = Field(default_factory=list)
    ready_for_matching: bool = False
    onboarding_step: int = 0
    onboarding_question: str | None = None
    saved_count: int = 0
    updated_at: datetime | None = None


class CardOut(BaseModel):
    match_id: str
    type: Literal["job", "talk"] = "job"
    title: str
    org: str | None = None
    location: str | None = None
    remote: bool = False
    salary: str | None = None
    score: float = 0.0
    reason: str | None = None
    summary: str | None = None
    url: str | None = None
    link_label: str | None = None
    source: str | None = None
    deadline: datetime | None = None
    saved: bool = False


class FeedOut(BaseModel):
    scope: Scope
    items: list[CardOut]
    refreshed: bool = False


class ReactionIn(BaseModel):
    reaction: Reaction


class ReactionOut(BaseModel):
    ok: bool
    effect: str
    learned: bool = False


class DraftOut(BaseModel):
    match_id: str
    kind: Literal["cover_letter", "talk_pitch"]
    text: str


class ErrorOut(BaseModel):
    """Единый формат ошибки: UI показывает `message`, логика смотрит на `code`."""

    code: str
    message: str
