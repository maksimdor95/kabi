#!/usr/bin/env python3
"""Применить миграции к БД из .env.

  PYTHONPATH=. python scripts/migrate.py          # ensure_schema (stamp|upgrade)
  PYTHONPATH=. python scripts/migrate.py upgrade  # только upgrade head
  PYTHONPATH=. python scripts/migrate.py stamp    # только stamp head
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Kabi DB migrations (M10)")
    p.add_argument(
        "action",
        nargs="?",
        default="ensure",
        choices=("ensure", "upgrade", "stamp"),
    )
    return p.parse_args()


async def _ensure() -> None:
    from app.db.migrate import ensure_schema
    from app.db.session import engine

    await ensure_schema(engine)
    await engine.dispose()


def main() -> int:
    args = _parse()
    if args.action == "ensure":
        asyncio.run(_ensure())
    elif args.action == "upgrade":
        from app.db.migrate import upgrade_head

        upgrade_head()
    else:
        from app.db.migrate import stamp_head

        stamp_head()
    print(f"OK ({args.action})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
