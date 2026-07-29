"""Доменная модель возможности. См. docs/architecture/data-model.md → Opportunity"""

from dataclasses import dataclass
from typing import Literal

OpportunityType = Literal["job", "talk"]


@dataclass
class Opportunity:
    type: OpportunityType
    title: str
    org: str | None = None
    description: str | None = None
    location: str | None = None
    remote: bool = False
    url: str | None = None
    source: str | None = None
    external_id: str | None = None
    # salary, deadline, embedding — добавим при реализации M2/M3
