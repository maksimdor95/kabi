"""Загрузка фикстур evals/matching."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EVALS_MATCHING = ROOT / "evals" / "matching"


def load_profile_fixture(name: str = "marina_v1") -> dict[str, Any]:
    path = EVALS_MATCHING / "profiles" / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_pool(name: str = "jobs_hh_sj_v1") -> list[dict[str, Any]]:
    path = EVALS_MATCHING / "pools" / f"{name}.jsonl"
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def load_filter_cases(name: str = "filter_negatives_v1") -> list[dict[str, Any]]:
    path = EVALS_MATCHING / "gold" / f"{name}.jsonl"
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def profile_from_fixture(data: dict[str, Any], **overrides: Any) -> SimpleNamespace:
    base = {
        "id": data.get("id"),
        "roles": list(data.get("roles") or []),
        "location": data.get("location"),
        "work_mode": data.get("work_mode"),
        "skills": list(data.get("skills") or []),
        "languages": list(data.get("languages") or []),
        "speaking_topics": list(data.get("speaking_topics") or []),
        "salary_expectation": data.get("salary_expectation"),
        "priorities": data.get("priorities") or "both",
        "hard_nos": data.get("hard_nos") or {},
        "experience": data.get("experience") or [],
        "goals": data.get("goals"),
        "embedding": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def opp_from_dict(data: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        id=data.get("id"),
        type=data.get("type") or "job",
        title=data.get("title") or "",
        org=data.get("org"),
        description=data.get("description") or "",
        location=data.get("location"),
        remote=bool(data.get("remote")),
        salary=data.get("salary"),
        deadline=data.get("deadline"),
        url=data.get("url"),
        source=data.get("source"),
        external_id=data.get("external_id"),
        meta=data.get("meta") or {},
        embedding=data.get("embedding"),
    )
