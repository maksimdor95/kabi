#!/usr/bin/env python3
"""Прогон matching evals (E1/E2/E3). Спека: docs/services/evals.md

  PYTHONPATH=. python scripts/run_matching_eval.py              # embed если есть кэш
  PYTHONPATH=. python scripts/run_matching_eval.py --mode lexical
  PYTHONPATH=. python scripts/run_matching_eval.py --mode embed --judge
  PYTHONPATH=. python scripts/run_matching_eval.py --calibrate-judge
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.evals.dataset import (  # noqa: E402
    load_filter_cases,
    load_pool,
    load_profile_fixture,
    opp_from_dict,
    profile_from_fixture,
)
from app.evals.embeddings import load_cache, rank_vector  # noqa: E402
from app.evals.judge import calibrate_lm_judge, evaluate_explain_lm  # noqa: E402
from app.evals.metrics import (  # noqa: E402
    EvalReport,
    Thresholds,
    apply_thresholds,
    evaluate_explain_heuristic,
    evaluate_filters,
    evaluate_ranking,
    rank_lexical,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Kabi matching evals (M8)")
    p.add_argument("--profile", default="marina_v1")
    p.add_argument("--pool", default="jobs_hh_sj_v1")
    p.add_argument("--filters", default="filter_negatives_v1")
    p.add_argument(
        "--mode",
        choices=("auto", "lexical", "embed"),
        default="auto",
        help="auto: embed если есть кэш, иначе lexical",
    )
    p.add_argument(
        "--judge",
        action="store_true",
        help="E2: LLM explain + LM-judge (нужен API)",
    )
    p.add_argument(
        "--explain-heuristic",
        action="store_true",
        help="E2 heuristic на stub reasons (без API)",
    )
    p.add_argument(
        "--calibrate-judge",
        action="store_true",
        help="Только калибровка LM-judge vs human gold (R1≥0.7)",
    )
    p.add_argument("--report-dir", default="evals/reports")
    p.add_argument("--no-write", action="store_true")
    return p.parse_args()


async def _llm_reasons(profile, top_rows: list[dict]) -> list[tuple[dict, str]]:
    from app.services import matching as matching_service

    out: list[tuple[dict, str]] = []
    for row in top_rows:
        opp = opp_from_dict(row)
        reason = await matching_service.explain(profile, opp)  # type: ignore[arg-type]
        out.append((row, reason))
    return out


async def _async_main(args: argparse.Namespace) -> int:
    th = Thresholds()
    fixture = load_profile_fixture(args.profile)
    profile = profile_from_fixture(fixture)

    if args.calibrate_judge:
        result = await calibrate_lm_judge(profile)
        print(
            f"calibrate R1 agreement={result['agreement_r1']:.2f} "
            f"n={result['n']} PASS={result['passed']}"
        )
        for pair in result["pairs"]:
            mark = "✓" if pair["human_r1"] == pair["judge_r1"] else "✗"
            print(
                f"  {mark} {pair['id']}: human={pair['human_r1']} "
                f"judge={pair['judge_r1']}"
            )
        if not args.no_write:
            out_dir = ROOT / args.report_dir
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / "judge_calibration.json"
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"report → {path}")
        return 0 if result["passed"] else 1

    pool = load_pool(args.pool)
    cases = load_filter_cases(args.filters)
    cache = load_cache(args.profile, args.pool)

    mode = args.mode
    if mode == "auto":
        mode = "embed" if cache else "lexical"
    if mode == "embed" and not cache:
        print("ERROR: embedding cache missing. Run scripts/build_eval_embedding_cache.py")
        return 2

    if mode == "embed":
        ranked, filtered_out = rank_vector(
            profile, pool, cache, top_n=max(th.top_n, th.recall_k)
        )
    else:
        ranked, filtered_out = rank_lexical(
            profile, pool, top_n=max(th.top_n, th.recall_k)
        )

    ranking = evaluate_ranking(
        profile, pool, thresholds=th, ranked=ranked, filtered_out=filtered_out
    )
    filters = evaluate_filters(profile, cases)

    explain = None
    require_explain = bool(args.judge or args.explain_heuristic)
    if args.judge:
        top_rows = [row for row, _ in ranked[: th.top_n]]
        pairs = await _llm_reasons(profile, top_rows)
        explain = await evaluate_explain_lm(profile, pairs)
    elif args.explain_heuristic:
        pairs = []
        for row, _ in ranked[: th.top_n]:
            roles = ", ".join((fixture.get("roles") or [])[:2])
            reason = (
                f"Роль близка к {roles}; в карточке «{row.get('title')}» "
                f"({row.get('org') or 'компания'}) пересекается с product/стратегией."
            )
            pairs.append((row, reason))
        explain = evaluate_explain_heuristic(profile, pairs)

    report = apply_thresholds(
        EvalReport(
            pool_version=args.pool,
            profile_id=args.profile,
            ranking=ranking,
            filters=filters,
            explain=explain,
        ),
        thresholds=th,
        require_explain=require_explain,
    )
    print(report.summary())
    print(f"mode={mode}")

    if not args.no_write:
        out_dir = ROOT / args.report_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = out_dir / f"{args.profile}_{args.pool}_{mode}_{stamp}.json"
        payload = {
            "passed": report.passed,
            "failures": report.failures,
            "profile_id": report.profile_id,
            "pool_version": report.pool_version,
            "mode": mode,
            "ranking": {
                "precision_at_n": ranking.precision_at_n,
                "noise_at_n": ranking.noise_at_n,
                "borderline_at_n": ranking.borderline_at_n,
                "recall_at_k": ranking.recall_at_k,
                "top": [
                    {"id": i, "label": lab, "score": sc}
                    for i, lab, sc in ranking.top_labels
                ],
                "hard_filtered_out": ranking.hard_filtered_out,
            },
            "filters": {
                "accuracy": filters.accuracy,
                "correct": filters.correct,
                "total": filters.total,
                "failures": filters.failures,
            },
            "explain": None
            if explain is None
            else {
                "sum_ge6_rate": explain.sum_ge6_rate,
                "r1_eq2_rate": explain.r1_eq2_rate,
                "r1_eq0_rate": explain.r1_eq0_rate,
                "scores": [
                    {
                        "id": s.item_id,
                        "r1": s.r1,
                        "r2": s.r2,
                        "r3": s.r3,
                        "r4": s.r4,
                        "total": s.total,
                        "reason": s.reason,
                    }
                    for s in explain.scores
                ],
            },
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"report → {path}")

    return 0 if report.passed else 1


def main() -> int:
    return asyncio.run(_async_main(_parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
