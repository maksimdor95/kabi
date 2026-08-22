# Модуль: multi-user (изоляция профилей)

## 1. Назначение
Контракт **уровня A**: несколько Telegram-пользователей в одном боте Kabi —
каждый со своим профилем, матчами и памятью. Общий каталог возможностей.

Это **не** SaaS (тенанты, биллинг, роли) — уровень B вне scope.

## 2. Этап
MU-A (после M10). Основа для M11: Mini App резолвит профиль из подписи
Telegram (`docs/services/miniapp.md` §5).

## 3. Модель

| Сущность | Скоуп |
|----------|--------|
| `User` (`telegram_id`) | персональный |
| `Profile` | персональный (1:1 User) |
| `Match`, `Feedback`, `DeadlineReminderLog` | персональный (`profile_id`) |
| Dialog memory (Redis) | персональный (`user_id`) |
| `digest_schedule` / digests | персональный; send → свой `telegram_id` |
| `Opportunity` | **общий** каталог |

## 4. Публичные правила (интерфейсы)

- Любая команда/текст: `from_user.id` → User → Profile.
- Mini App: `telegram_id` берётся только из проверенной подписи `initData`,
  никогда из тела запроса.
- Callback `fb:*` / `draft:*` и ручки `/api/v1/matches/{id}/*`: реакция/черновик
  только если `match.profile_id == actor.profile.id`. Иначе отказ (`forbidden`
  → `403`), без записи. Проверка в сервисах `feedback` и `drafts`, чтобы канал
  нельзя было обойти.
- `/delete`: только свой User/Profile/Match/Feedback/reminders/CV/memory.
  Opportunity не трогаем.

## 5. Acceptance (evals / тесты)

| ID | Критерий |
|----|----------|
| I1 | Два telegram_id → два Profile |
| I2 | saved/matches одного не видны в API другого |
| I3 | Callback/HTTP на чужой match_id → `ok=False` / `403`, статус и embedding чужого не меняются |
| I4 | delete A не удаляет Profile B |
| I5 | Scheduler шлёт на telegram_id владельца профиля (контракт кода) |
| I6 | Dialog memory keyed by user_id |
| I7 | Enrichment только по своим ссылкам (уже hard rule) |

Unit: `tests/test_multiuser_isolation.py`, HTTP-срез — `tests/test_miniapp_api.py`.

## 6. Guardrails

- Нет «списка всех профилей» в боте.
- Нет сбора данных о третьих лицах (AGENTS.md).
- Один `TELEGRAM_BOT_TOKEN`: два локальных polling = Conflict (ops, не data leak).

## 7. Вне scope (уровень B)

Мультитенантность, allowlist «только семья», admin `/users`, квоты LLM,
биллинг, success fee.

## 8. Статус
MU-A: спека + проверка владельца в `feedback.record_reaction` и
`drafts.draft_for_match` + тесты. M11 наследует контракт без изменений.
