#!/usr/bin/env python3
"""Прогон advisor evals (M9). Спека: docs/services/dialogue-agent.md

  PYTHONPATH=. python scripts/run_advisor_eval.py              # только tools-контракт
  PYTHONPATH=. python scripts/run_advisor_eval.py --llm         # + ответы модели
  PYTHONPATH=. python scripts/run_advisor_eval.py --llm --judge # + LM-judge
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

from app.evals.advisor import run_pool  # noqa: E402


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Kabi advisor dialogue evals (M9)")
    p.add_argument("--llm", action="store_true", help="Сгенерировать ответы (нужен API)")
    p.add_argument("--judge", action="store_true", help="LM-judge (нужен --llm и API)")
    p.add_argument("--report-dir", default="evals/reports")
    p.add_argument("--no-write", action="store_true")
    return p.parse_args()


async def _main() -> int:
    args = _parse_args()
    if args.judge and not args.llm:
        print("--judge требует --llm", file=sys.stderr)
        return 2

    results = await run_pool(with_llm=args.llm, with_judge=args.judge)
    tools_fail = sum(1 for r in results if not r.tools_ok)
    judge_fail = sum(1 for r in results if r.judge_pass is False)
    n = len(results)

    for r in results:
        mark = "✓" if r.tools_ok and r.judge_pass is not False else "✗"
        extra = ""
        if r.judge_pass is not None:
            extra = f" judge={'pass' if r.judge_pass else 'fail'}({r.judge_notes})"
        print(f"  {mark} {r.case_id}: tools={r.got_tools}{extra}")
        for err in r.errors:
            print(f"      · {err}")

    print(
        f"\ntools_ok={n - tools_fail}/{n} "
        f"judge_fail={judge_fail if args.judge else 'n/a'}"
    )

    if not args.no_write:
        out_dir = ROOT / args.report_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = out_dir / f"advisor_m9_{stamp}.json"
        payload = {
            "ts": stamp,
            "llm": args.llm,
            "judge": args.judge,
            "tools_fail": tools_fail,
            "judge_fail": judge_fail,
            "cases": [
                {
                    "id": r.case_id,
                    "tools_ok": r.tools_ok,
                    "expect_tools": r.expect_tools,
                    "got_tools": r.got_tools,
                    "judge_pass": r.judge_pass,
                    "judge_notes": r.judge_notes,
                    "reply": r.reply,
                    "errors": r.errors,
                }
                for r in results
            ],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"report: {path}")

    if tools_fail:
        return 1
    if args.judge and judge_fail:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
