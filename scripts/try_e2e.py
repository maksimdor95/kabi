"""Сквозная симуляция /start → CV → онбординг против реального Postgres + Yandex.

Проигрывает тот же код сервисов, что и бот, но без Telegram.
Запуск: PYTHONPATH=. python scripts/try_e2e.py <path-to-cv>
"""

import asyncio
import sys

from app.db.session import SessionFactory, engine, init_db
from app.services import cv_parser, dialogue_agent
from app.services import profile as profile_service
from app.services.onboarding import STEPS

ANSWERS_BY_KEY = {
    "consent_links": "да, вот https://hh.ru/resume/example и https://linkedin.com/in/example",
    "priorities": "оба",
    "salary": "от 500 000 руб",
    "hard_nos": "не хочу в гемблинг и табак",
}

TG_ID = 123456789


async def _wait_db(retries: int = 15) -> None:
    for i in range(retries):
        try:
            await init_db()
            return
        except Exception as exc:  # noqa: BLE001
            print(f"  ждём Postgres ({i + 1})… {type(exc).__name__}")
            await asyncio.sleep(2)
    raise RuntimeError("Postgres недоступен")


async def main(cv_path: str) -> None:
    print("1) init_db")
    await _wait_db()

    print("2) /start → создаём пользователя")
    async with SessionFactory() as s:
        user = await profile_service.get_or_create_user(s, TG_ID)
        await s.commit()
        user_id = user.id
    print(f"   user_id={user_id}")

    print("3) загрузка CV → парсинг → профиль → старт онбординга")
    draft = await cv_parser.parse_cv(cv_path)
    async with SessionFactory() as s:
        prof = await profile_service.apply_cv_draft(s, user_id, draft, raw_cv_ref=cv_path)
        reply = await dialogue_agent.start_onboarding(s, prof)
        await s.commit()
    print(f"   salary_from_cv={draft.salary_expectation}")
    print(f"   Q0: {reply.text}")

    print("4) онбординг: проигрываем ответы по текущему шагу")
    for _ in range(len(STEPS) + 2):
        async with SessionFactory() as s:
            user = await profile_service.get_or_create_user(s, TG_ID)
            prof = await profile_service.get_profile(s, user.id)
            if prof is None or dialogue_agent.is_onboarding_complete(prof):
                break
            step = STEPS[prof.onboarding_step]
            ans = ANSWERS_BY_KEY.get(step.key)
            if not ans:
                print(f"   нет ответа для шага {step.key}")
                break
            reply = await dialogue_agent.handle_message(s, user, ans)
            await s.commit()
        print(f"   >> [{step.key}] {ans}")
        print(f"   << {reply.text}  [finished={reply.finished}]")
        if reply.finished:
            break

    print("5) эмбеддинг профиля + итог")
    async with SessionFactory() as s:
        prof = await profile_service.get_profile(s, user_id)
        await profile_service.compute_embedding(s, prof)
        await s.commit()
        print(f"   ready_for_matching={prof.ready_for_matching}")
        print(f"   priorities={prof.priorities} status={prof.job_search_status}")
        print(f"   salary={prof.salary_expectation}")
        print(f"   consent={prof.enrichment_consent} links={prof.source_links}")
        print(f"   embedding_dim={len(prof.embedding) if prof.embedding is not None else None}")

    await engine.dispose()
    print("OK")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
