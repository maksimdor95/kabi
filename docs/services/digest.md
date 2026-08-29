# Модуль: digest

## 1. Назначение
Проактивная доставка: собирает ежедневную подборку лучших матчей и отправляет
пользователю карточками. Это то, ради чего продукт существует — «менеджер сам приносит».

## 2. Этап
M2 (ежедневная подборка), M3 (напоминания о дедлайнах).

## 3. Публичный интерфейс
```python
async def build_digest(session, profile, *, scope, do_ingest=True, limit=7, …) -> list[DigestItem]: ...
async def list_pending(session, profile, *, scope, limit=7) -> list[DigestItem]: ...
async def mark_shown(session, match_ids) -> int: ...
async def deliver_feed(session, profile, items, *, scope, channel) -> list[DigestItem]: ...
```
`scope`: `jobs` | `pitch` | `talks`.
`channel`: `bot` | `miniapp` | `scheduler` | `advisor`.

- `build_digest` — создать **новые** Match (опционально с ingest). Возвращает
  только что созданные; если кандидаты уже сматчены раньше → `[]`.
- `list_pending` — витрина: уже существующие `Match.status=new` по scope
  (то, на что ещё не было реакции). Так работает Mini App: открытие не
  выглядит пустым, пока в карманах бота лежат неотреагированные карточки.
- `deliver_feed` — единая точка показа: `mark_shown` + `digest_shown` или
  `empty_state` (см. `docs/services/analytics.md`).

Поля карточки (`app/services/cards.py`) — presentation-neutral и общие для всех
каналов: `format_salary`, `card_title`, `card_summary`, `reason_snippet`,
`format_source_label`. Разметку добавляет канал: HTML в `bot/keyboards`,
JSON в `app/api`.

## 4. Входы / Выходы
- **Вход:** профиль + свежие `Match`.
- **Выход:** `DigestItem` → карточки в Telegram или в Mini App.

## 5. Зависимости
- **Внутренние:** `app/db`, `app/services/matching`, `app/ingestion`,
  `app/services/schedule`; потребители — `bot`, `app/api`, `app/scheduler`.
- **Внешние:** —

## 6. Данные
Читает `Match` (status=`new`), помечает доставленные.

## 7. Guardrails / ограничения
- Не спамить: лимит карточек в день, не повторять уже показанное.
- Пустая подборка → честное «сегодня ничего стоящего», а не мусор.

## 8. Тесты / evals
- **Тест:** сборка подборки уважает лимит и не включает скрытые/показанные.

## 9. Открытые вопросы
- Время доставки; частота (ежедневно/по мере появления сильных матчей).

## 10. Статус
M2/M3 в проде: `/today`, `/pitch`, `/talks` + рассылка по расписанию.
M11: `GET /api/v1/feed` → `list_pending` + `deliver_feed`; `POST /feed/refresh` →
`build_digest` + витрина. Pitch 2.0: блок «Как зайти», CTA без homepage.
Общие поля карточки в `app/services/cards.py`. См. `docs/services/pitch.md`.
P1: impressions/empty через `deliver_feed` → `product_events`.
