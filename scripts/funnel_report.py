#!/usr/bin/env python3
"""Воронка product_events (Sprint A).

  PYTHONPATH=. python scripts/funnel_report.py
  PYTHONPATH=. python scripts/funnel_report.py --days 30

Читает DATABASE из env (.env / .env.staging уже в окружении).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


async def _run(days: int) -> None:
    from sqlalchemy import text
    from app.db.session import engine

    sql = text(
        """
        with windowed as (
          select name, props, profile_id, created_at
          from product_events
          where created_at > now() - make_interval(days => :days)
        )
        select name, count(*) as n, count(distinct profile_id) as profiles
        from windowed
        group by name
        order by n desc
        """
    )
    funnel_order = [
        "session_started",
        "entry_chosen",
        "cv_uploaded",
        "onboarding_step_entered",
        "onboarding_step_completed",
        "digest_shown",
        "card_reacted",
        "empty_state",
    ]
    async with engine.connect() as conn:
        rows = (await conn.execute(sql, {"days": days})).all()
    by_name = {r[0]: (r[1], r[2]) for r in rows}
    print(f"=== funnel last {days}d ===")
    for name in funnel_order:
        n, p = by_name.get(name, (0, 0))
        print(f"{name:28} events={n:5} profiles={p}")
    print("--- other ---")
    for name, (n, p) in sorted(by_name.items(), key=lambda x: -x[1][0]):
        if name not in funnel_order:
            print(f"{name:28} events={n:5} profiles={p}")

    # entries breakdown
    async with engine.connect() as conn:
        entries = (
            await conn.execute(
                text(
                    """
                    select coalesce(props->>'entry','?'), count(*)
                    from product_events
                    where name='entry_chosen'
                      and created_at > now() - make_interval(days => :days)
                    group by 1 order by 2 desc
                    """
                ),
                {"days": days},
            )
        ).all()
    print("=== entry_chosen ===")
    for e, n in entries:
        print(f"  {e}: {n}")
    await engine.dispose()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=14)
    p.add_argument("--env-file", default=".env.staging")
    args = p.parse_args()
    _load_dotenv(ROOT / args.env_file)
    _load_dotenv(ROOT / ".env")
    asyncio.run(_run(args.days))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
