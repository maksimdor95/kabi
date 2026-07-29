#!/usr/bin/env python3
"""Построить кэш эмбеддингов для matching eval (нужен Yandex API).

  PYTHONPATH=. python scripts/build_eval_embedding_cache.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.evals.dataset import load_pool, load_profile_fixture, profile_from_fixture
from app.evals.embeddings import build_cache


async def _run(profile_id: str, pool_version: str) -> None:
    fixture = load_profile_fixture(profile_id)
    profile = profile_from_fixture(fixture)
    pool = load_pool(pool_version)
    path = await build_cache(
        profile, pool, profile_id=profile_id, pool_version=pool_version
    )
    print(f"cache → {path} items={len(pool)}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", default="marina_v1")
    p.add_argument("--pool", default="jobs_hh_sj_v1")
    args = p.parse_args()
    asyncio.run(_run(args.profile, args.pool))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
