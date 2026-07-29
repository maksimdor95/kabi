"""Доменная модель профиля. См. docs/architecture/data-model.md → Profile

Контракт готовности к мэтчингу (`ready_for_matching`) — в docs/services/profile.md.
"""

from dataclasses import dataclass, field
from typing import Literal

Priorities = Literal["job", "talk", "both"]
JobSearchStatus = Literal["active", "passive", "top_only"]


@dataclass
class SalaryExpectation:
    min: int
    currency: str = "RUB"
    comfortable: int | None = None


@dataclass
class Profile:
    user_id: str
    skills: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    location: str | None = None
    languages: list[str] = field(default_factory=list)
    work_mode: str | None = None  # remote | hybrid | office
    speaking_topics: list[str] = field(default_factory=list)
    goals: str | None = None

    # заполняется в онбординге (см. dialogue-agent.md)
    salary_expectation: SalaryExpectation | None = None  # обязательно для мэтчинга
    priorities: Priorities = "both"  # дефолт: оба, вакансии первыми
    job_search_status: JobSearchStatus = "passive"
    hard_nos: dict = field(default_factory=dict)  # анти-предпочтения
    availability: dict = field(default_factory=dict)  # занятость, срок выхода

    # enrichment (см. enrichment.md)
    enrichment_consent: bool = False
    source_links: list[str] = field(default_factory=list)

    def is_ready_for_matching(self) -> bool:
        """Обязательные поля заполнены (см. profile.md → контракт готовности)."""
        return bool(
            self.roles
            and self.location
            and self.work_mode
            and self.salary_expectation
            and self.skills
            and self.enrichment_consent
        )


@dataclass
class ProfileDraft:
    """Черновик профиля, извлечённый из CV (до онбординга и записи в БД)."""

    roles: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    location: str | None = None
    languages: list[str] = field(default_factory=list)
    work_mode: str | None = None
    experience: list[dict] = field(default_factory=list)
    speaking_topics: list[str] = field(default_factory=list)
    goals: str | None = None
    salary_expectation: dict | None = None  # {min, currency} если есть в CV
