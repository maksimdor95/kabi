"""Сигналы обогащения профиля (чистые типы без импортов источников)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ProfileSignals:
    """Кандидаты-поля для профиля. Записываются только после подтверждения пользователем."""

    speaking_topics: list[str] = field(default_factory=list)
    extra_skills: list[str] = field(default_factory=list)
    job_search_status: str | None = None  # active | passive | top_only
    source_links: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
