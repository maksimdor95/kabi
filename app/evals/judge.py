"""LM-judge для E2 (evals.md §8.2). Калибровка vs human gold."""

from __future__ import annotations

import json
import re
from types import SimpleNamespace
from typing import Any

from app.evals.dataset import EVALS_MATCHING
from app.evals.metrics import ExplainResult, ExplainScore, profile_text

_JUDGE_SYSTEM = """Ты — строгий оценщик объяснений карьерного мэтчинга.
Оцени reason по rubric 0–2. Верни ТОЛЬКО один JSON-объект без markdown:
{"r1":0,"r2":0,"r3":0,"r4":0,"brief":"ok"}
Значения r1..r4 — целые 0, 1 или 2. brief — одно короткое слово латиницей без кавычек внутри.

R1 Факты: 2 = только факты из профиля/карточки; 0 = выдумка.
R2 Специфика: 2 = ≥2 якоря; 0 = вода / fallback «совпадение по роли».
R3 Честность fit: 0 = приукрашивает явный мисфит.
R4 Полезность: помогает ли решить открыть карточку.

Fallback «Совпадение по роли и ключевым навыкам» → r2=0, r1=2.
"""


def load_judge_gold(name: str = "explain_human_v1") -> list[dict[str, Any]]:
    path = EVALS_MATCHING / "gold" / f"{name}.jsonl"
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def agreement_r1(
    human: list[ExplainScore], predicted: list[ExplainScore]
) -> float:
    """Доля совпадений R1 (калибровка ≥0.7 по спеке)."""
    if not human:
        return 0.0
    by_id = {s.item_id: s for s in predicted}
    ok = 0
    for h in human:
        p = by_id.get(h.item_id)
        if p is not None and p.r1 == h.r1:
            ok += 1
    return ok / len(human)


def _clamp_score(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(2, n))


def _parse_judge_payload(raw: str | dict[str, Any]) -> dict[str, int]:
    data: dict[str, Any] = {}
    if isinstance(raw, dict):
        data = dict(raw)
    else:
        text = (raw or "").strip()
        try:
            from app.llm.client import _parse_json_loose

            parsed = _parse_json_loose(text)
            if isinstance(parsed, dict):
                data = parsed
        except Exception:
            data = {}
        if not all(k in data for k in ("r1", "r2", "r3", "r4")):
            for key in ("r1", "r2", "r3", "r4"):
                m = re.search(rf'"{key}"\s*:\s*([0-2])', text)
                if m:
                    data[key] = int(m.group(1))
            if not all(k in data for k in ("r1", "r2", "r3", "r4")):
                for key in ("r1", "r2", "r3", "r4"):
                    if key in data:
                        continue
                    m = re.search(rf"{key}\"?\s*[:=]\s*([0-2])", text, re.I)
                    if m:
                        data[key] = int(m.group(1))
    return {
        "r1": _clamp_score(data.get("r1", 0)),
        "r2": _clamp_score(data.get("r2", 0)),
        "r3": _clamp_score(data.get("r3", 0)),
        "r4": _clamp_score(data.get("r4", 0)),
    }


async def lm_judge_one(
    profile: SimpleNamespace,
    row: dict[str, Any],
    reason: str,
    *,
    tier: str = "cheap",
) -> ExplainScore:
    from app.llm import client as llm

    prompt = (
        f"ПРОФИЛЬ:\n{profile_text(profile)}\n\n"
        f"КАРТОЧКА:\n"
        f"title: {row.get('title')}\n"
        f"org: {row.get('org')}\n"
        f"label: {row.get('label')}\n"
        f"description: {(row.get('description') or '')[:500]}\n\n"
        f"REASON:\n{reason}\n"
    )
    raw = await llm.complete(
        prompt, system=_JUDGE_SYSTEM, tier=tier, temperature=0.0, max_tokens=200
    )  # type: ignore[arg-type]
    data = _parse_judge_payload(raw)
    return ExplainScore(
        item_id=str(row.get("id") or ""),
        reason=reason,
        r1=data["r1"],
        r2=data["r2"],
        r3=data["r3"],
        r4=data["r4"],
    )


async def evaluate_explain_lm(
    profile: SimpleNamespace,
    items: list[tuple[dict[str, Any], str]],
    *,
    tier: str = "cheap",
) -> ExplainResult:
    scores: list[ExplainScore] = []
    for row, reason in items:
        scores.append(await lm_judge_one(profile, row, reason, tier=tier))
    n = len(scores) or 1
    return ExplainResult(
        scores=scores,
        sum_ge6_rate=sum(1 for s in scores if s.total >= 6) / n,
        r1_eq2_rate=sum(1 for s in scores if s.r1 == 2) / n,
        r1_eq0_rate=sum(1 for s in scores if s.r1 == 0) / n,
    )


def gold_to_scores(rows: list[dict[str, Any]]) -> list[ExplainScore]:
    return [
        ExplainScore(
            item_id=str(r["id"]),
            reason=r.get("reason") or "",
            r1=int(r["human"]["r1"]),
            r2=int(r["human"]["r2"]),
            r3=int(r["human"]["r3"]),
            r4=int(r["human"]["r4"]),
        )
        for r in rows
    ]


async def calibrate_lm_judge(
    profile: SimpleNamespace,
    gold_rows: list[dict[str, Any]] | None = None,
    *,
    tier: str = "cheap",
) -> dict[str, Any]:
    """Сравнить LM-judge с human gold по R1. Pass если agreement ≥ 0.7."""
    gold_rows = gold_rows or load_judge_gold()
    human = gold_to_scores(gold_rows)
    predicted: list[ExplainScore] = []
    for row in gold_rows:
        card = {
            "id": row["id"],
            "title": row.get("title"),
            "org": row.get("org"),
            "description": row.get("description"),
            "label": row.get("label"),
        }
        predicted.append(
            await lm_judge_one(profile, card, row["reason"], tier=tier)
        )
    agr = agreement_r1(human, predicted)
    return {
        "agreement_r1": agr,
        "passed": agr >= 0.7,
        "n": len(human),
        "pairs": [
            {
                "id": h.item_id,
                "human_r1": h.r1,
                "judge_r1": next(
                    (p.r1 for p in predicted if p.item_id == h.item_id), None
                ),
            }
            for h in human
        ],
    }
