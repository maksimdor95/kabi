"""Единый интерфейс коннектора вакансий. Спека: docs/services/ingestion.md

Коннектор принимает поисковые ключевые слова (выведенные из профиля) и
возвращает нормализованные OpportunityDraft. Он не ходит в БД и не считает
эмбеддинги — этим занимается runner.
"""

from typing import Protocol

from app.ingestion.schemas import OpportunityDraft


class JobConnector(Protocol):
    source: str

    async def fetch(self, keywords: list[str], *, area: int | None = None) -> list[OpportunityDraft]:
        """Забрать и нормализовать вакансии по ключевым словам."""
        ...
