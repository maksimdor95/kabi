"""Кэш эмбеддингов для E1 vector-rank. Спека: docs/services/evals.md §9.3."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.evals.dataset import EVALS_MATCHING, opp_from_dict
from app.evals.metrics import Thresholds, cosine, opp_text, profile_text
from app.services.matching import passes_hard_filters

CACHE_DIR = EVALS_MATCHING / "cache"


def cache_path(profile_id: str, pool_version: str) -> Path:
    return CACHE_DIR / f"{profile_id}__{pool_version}.json"


def load_cache(profile_id: str, pool_version: str) -> dict[str, Any] | None:
    path = cache_path(profile_id, pool_version)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_cache(profile_id: str, pool_version: str, payload: dict[str, Any]) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = cache_path(profile_id, pool_version)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def opp_embed_text(row: dict[str, Any]) -> str:
    """Паритет с OpportunityDraft.to_text() (ingestion)."""
    parts = [
        row.get("title") or "",
        row.get("org") or "",
        row.get("location") or "",
        "удалённо" if row.get("remote") else "",
        row.get("description") or "",
    ]
    return "\n".join(p for p in parts if p).strip()


async def build_cache(
    profile: SimpleNamespace,
    pool: list[dict[str, Any]],
    *,
    profile_id: str,
    pool_version: str,
) -> Path:
    """Посчитать query/doc эмбеддинги и сохранить кэш (нужен LLM API)."""
    from app.llm import client as llm

    p_text = profile_text(profile)
    profile_vec = await llm.embed(p_text, kind="query")

    items: dict[str, list[float]] = {}
    for row in pool:
        text = opp_embed_text(row)
        if not text:
            continue
        items[row["id"]] = await llm.embed(text, kind="doc")

    payload = {
        "profile_id": profile_id,
        "pool_version": pool_version,
        "embed_dim": len(profile_vec),
        "profile_text": p_text,
        "profile_embedding": profile_vec,
        "items": items,
    }
    return save_cache(profile_id, pool_version, payload)


def rank_vector(
    profile: SimpleNamespace,
    pool: list[dict[str, Any]],
    cache: dict[str, Any],
    *,
    top_n: int | None = None,
    apply_hard_filters: bool = True,
) -> tuple[list[tuple[dict[str, Any], float]], int]:
    """Ранжирование cosine(query, doc) как в pgvector (score = similarity)."""
    th = Thresholds()
    th_n = top_n or max(th.top_n, th.recall_k)
    profile_vec = cache.get("profile_embedding")
    items = cache.get("items") or {}
    if not profile_vec or not items:
        raise ValueError("embedding cache empty")

    by_id = {r["id"]: r for r in pool}
    scored: list[tuple[dict[str, Any], float]] = []
    filtered_out = 0
    for iid, vec in items.items():
        row = by_id.get(iid)
        if row is None:
            continue
        opp = opp_from_dict(row)
        if apply_hard_filters and not passes_hard_filters(opp, profile):  # type: ignore[arg-type]
            filtered_out += 1
            continue
        score = round(cosine(profile_vec, vec), 4)
        scored.append((row, score))

    # Пул без вектора в кэше — в конец с 0 (не должны попадать в топ)
    for row in pool:
        if row["id"] in items:
            continue
        opp = opp_from_dict(row)
        if apply_hard_filters and not passes_hard_filters(opp, profile):  # type: ignore[arg-type]
            filtered_out += 1
            continue
        scored.append((row, 0.0))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:th_n], filtered_out
