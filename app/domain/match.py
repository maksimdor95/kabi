"""Доменные модели матча и фидбека. См. docs/architecture/data-model.md"""

from dataclasses import dataclass
from typing import Literal

MatchStatus = Literal["new", "liked", "hidden", "applied"]
Reaction = Literal["up", "down", "hide", "save"]


@dataclass
class Match:
    profile_id: str
    opportunity_id: str
    score: float
    reason: str
    status: MatchStatus = "new"
