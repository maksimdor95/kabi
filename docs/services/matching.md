# Модуль: matching

## 1. Назначение
Сопоставляет профиль с возможностями: векторное сходство + хард-фильтры +
ранжирование, и генерирует объяснение «почему это тебе подходит».

## 2. Этап
M2.

## 3. Публичный интерфейс
```python
async def match(profile: Profile, candidates: list[Opportunity]) -> list[Match]: ...
async def explain(profile: Profile, opp: Opportunity) -> str: ...
```

## 4. Входы / Выходы
- **Вход:** профиль (+эмбеддинг), пул возможностей (+эмбеддинги).
- **Выход:** ранжированные `Match` со `score` и `reason`.

## 5. Зависимости
- **Внутренние:** `app/db` (pgvector-поиск), `app/llm` (объяснения).
- **Внешние:** pgvector.

## 6. Данные
Читает `Profile`, `Opportunity`; пишет `Match`.

## 7. Guardrails / ограничения
- Хард-фильтры (локация, remote, язык, зарплатный минимум, дедлайн) до ранжирования.
- Порог релевантности: лучше меньше, но точнее (доверие к «менеджеру» хрупко).
- Объяснение опирается только на реальные поля профиля/возможности (без выдумок).

## 8. Тесты / evals
- **Тест:** хард-фильтры отсекают неподходящее (`tests/test_matching_filters.py`).
- **Eval (M8 ✅):** `docs/services/evals.md` + `evals/matching/` +
  `scripts/run_matching_eval.py` (E1 vector/lexical, E2 LM-judge, E3 filters).

## 9. Открытые вопросы
- Модель эмбеддингов; вес семантики vs хард-критериев в итоговом score.

## 10. Статус
реализовано (M2): `app/services/matching.py` — pgvector cosine + хард-фильтры
(remote, зарплатный минимум, hard-nos), топ-N, LLM-объяснение (cheap tier),
дедуп уже показанных `Match`. Объяснения считаются **параллельно** (`asyncio.gather`).

Talks (M3+): дополнительно отсекаем `meta.status in {closed, watch}`, прошедший
deadline и отсутствие пересечения тем (`speaking_topics`/`roles`/`skills` ∩ `meta.topics`).

Потоки (lane):
- `/today` / утренняя рассылка: только **вакансии** (`scope=jobs`).
- `/pitch`: только **evergreen-питч** (`is_evergreen_pitch`) — СМИ/подкасты без дедлайна.
- `/talks`: конференции с реальной датой CFP (`deadlines.list_upcoming`).

M4: ranking использует `Profile.embedding`, который сдвигается реакциями 👍/👎
(см. `feedback.md` — онлайн-бленд).

Режим отбора (`Profile.digest_schedule.rank_mode`, см. `scheduler.md`):
- `fresh_relevant` (дефолт): blend similarity + recency(`fetched_at`);
- `relevant`: только cosine. Watch-доставка дополнительно режет по возрасту
  (`max_age_hours`).

Хард-фильтры jobs (CPO/HoP-трек): отсекаем явный tech IC (backend/devops/…)
и «менеджер проектов» без product-сигнала в title/description.
