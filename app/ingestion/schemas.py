"""Нормализованный черновик возможности на выходе коннектора.

Коннектор ничего не знает про БД — он возвращает список OpportunityDraft,
а runner (app/ingestion/runner.py) уже маппит их в ORM и считает эмбеддинги.
Спека: docs/services/ingestion.md (этап M2)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class OpportunityDraft:
    type: str  # job | talk
    title: str
    org: str | None = None
    description: str | None = None
    location: str | None = None
    remote: bool = False
    salary: dict | None = None  # {"min": int|None, "max": int|None, "currency": str}
    url: str | None = None
    source: str | None = None
    external_id: str | None = None
    posted_at: datetime | None = None
    deadline: datetime | None = None  # CFP / дедлайн заявки (M3)
    tags: list[str] | None = None
    meta: dict | None = None

    def to_text(self) -> str:
        """Текст для эмбеддинга (kind=doc)."""
        tags = " ".join(self.tags or [])
        parts = [
            self.title,
            self.org or "",
            self.location or "",
            "удалённо" if self.remote else "",
            tags,
            self.description or "",
        ]
        return "\n".join(p for p in parts if p).strip()
