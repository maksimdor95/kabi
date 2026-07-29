"""Evals подборки и объяснений. Спека: docs/services/evals.md"""

from __future__ import annotations

from app.evals.dataset import (
    load_filter_cases,
    load_pool,
    load_profile_fixture,
    opp_from_dict,
    profile_from_fixture,
)
from app.evals.metrics import (
    EvalReport,
    Thresholds,
    evaluate_explain_heuristic,
    evaluate_filters,
    evaluate_ranking,
    rank_lexical,
)

__all__ = [
    "EvalReport",
    "Thresholds",
    "evaluate_explain_heuristic",
    "evaluate_filters",
    "evaluate_ranking",
    "load_filter_cases",
    "load_pool",
    "load_profile_fixture",
    "opp_from_dict",
    "profile_from_fixture",
    "rank_lexical",
]
