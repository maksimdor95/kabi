# Модуль: scheduler

## 1. Назначение
Двигатель проактивности: по расписанию / мониторингу запускает core loop
(ingestion → matching → digest) и напоминания о дедлайнах.

## 2. Этап
M2 (ежедневный loop), M3 (дедлайны), M6b (настраиваемое расписание),
M6b+ (режимы доставки watch/scheduled + отбор fresh_relevant).

## 3. Публичный интерфейс
```python
def start_scheduler(bot: Bot) -> AsyncIOScheduler: ...
async def scheduled_digests(bot: Bot) -> None: ...   # тик */15 мин
async def deadline_reminders(bot: Bot) -> None: ...
# app/services/schedule.py — normalize / is_channel_due / is_watch_due /
#   is_quiet_hours / parse / format
```

## 4. Расписание профиля
Поле `Profile.digest_schedule` (JSONB), дефолт:

| Поле | Значение |
|------|----------|
| **delivery** | `watch` (мониторинг) или `scheduled` (слоты) |
| **rank_mode** | `fresh_relevant` (дефолт) или `relevant` |
| **quiet_hours** | `{start: 23, end: 8}` — не слать в watch |
| **watch_daily_limit** | 10 карточек/день на канал |
| **watch_batch_limit** | 3 карточки за тик |
| **jobs** | будни 09:00 (слот для scheduled / запасной) |
| **talks** | среда 17:00 |

### delivery=watch
Тик `*/15` мин: если канал вкл, не тихие часы и лимит дня не исчерпан —
лёгкий ingest → match **новых** (ещё без Match), `max_age_hours=72`,
пачка до `watch_batch_limit`. Пустая пачка **не** тратит лимит.
Счётчик: `last_digest_at.{channel}_watch_day` / `_watch_count`.

### delivery=scheduled
Как раньше: день + окно ±15 мин от :hour:minute, один раз в календарный день.
Пустая подборка тоже помечается sent.

### rank_mode
- `fresh_relevant`: score = 0.65·similarity + 0.35·recency(`fetched_at`, half-life 72h)
- `relevant`: только cosine similarity

Настройка: `/schedule` или фразы «мониторинг вкл», «по расписанию»,
«вакансии будни 9:00», «режим свежие», «тихие часы 23:00-8:00»,
«выступления выкл». Нужен явный сигнал (время / вкл-выкл / слово режима).
Фразы вроде «хочу выступления в среду» без времени — не расписание.

## 5. Зависимости
- **Внутренние:** `digest`, `matching`, `schedule`, `deadlines`.
- **Внешние:** APScheduler.

## 6. Guardrails
- Watch: не спамить — тихие часы + дневной лимит + батч 1–3.
- Scheduled: не слать дважды в один календарный день (канал).
- Уже показанные Match не повторяются.

## 7. Статус
Реализовано: тик watch/scheduled, quiet hours, rank_mode, дедлайны 10:00 МСК.
Ручные `/today`, `/pitch`, `/talks` без изменения доставки; отбор берут
`rank_mode` из профиля.
