# Архитектура Kabi — обзор

> Карта системы и границы модулей. Держим этот файл в статическом контексте агента.
> Детали каждого модуля — в `docs/services/<module>.md`.

## Стиль архитектуры

**Модульный монолит.** Один разворачиваемый процесс, жёсткие внутренние границы
модулей. Причины и trade-offs — в `decisions/0001-modular-monolith.md`.

Kabi — это **AI-агент-продукт**. Проектируем через пять частей агента:

| Часть агента | Где живёт в Kabi |
|--------------|------------------|
| **Model** (движок рассуждения) | `app/llm` |
| **Tools** (связь с миром) | `app/ingestion`, `app/services/*` как инструменты агента |
| **Memory** (состояние) | `app/db` (профиль, матчи, фидбек) + Redis (сессии) |
| **Orchestration** (цикл) | `app/services/dialogue_agent` + `app/scheduler` |
| **Deployment** | Docker Compose, `app/main.py`, `bot/main.py` |

## Слои и зависимости

Зависимости направлены **внутрь** (к домену). Домен ничего не знает об инфраструктуре.

```
┌───────────────────────────────────────────────┐
│  Интерфейс:  bot/  (Telegram, aiogram)          │  тонкий слой, без бизнес-логики
└───────────────────────┬─────────────────────────┘
                        ▼
┌───────────────────────────────────────────────┐
│  Прикладной слой:  app/services/*               │  сценарии, оркестрация агента
│   dialogue_agent · profile · enrichment         │
│   matching · digest · feedback · drafts         │
└──────────┬───────────────────────┬──────────────┘
           ▼                       ▼
┌────────────────────┐   ┌────────────────────────┐
│  Домен: app/domain │   │  Инфраструктура:        │
│  Profile · Opport. │   │  app/db · app/llm       │
│  Match · Feedback  │   │  app/ingestion          │
│  (чистые модели)   │   │  app/scheduler          │
└────────────────────┘   │  app/observability      │
                         └────────────────────────┘
```

## Карта модулей

| Модуль | Слой | Ответственность | Этап | Спека |
|--------|------|-----------------|------|-------|
| `bot` | интерфейс | Telegram: хендлеры, клавиатуры, рендер | M1 | [bot.md](../services/bot.md) |
| `dialogue_agent` | приложение | Агентный цикл: онбординг и общение «как менеджер» | M1 | [dialogue-agent.md](../services/dialogue-agent.md) |
| `profile` | приложение | Профиль пользователя + парсинг CV | M1 | [profile.md](../services/profile.md) |
| `enrichment` | приложение | Обогащение профиля из публичных источников пользователя | M1 | [enrichment.md](../services/enrichment.md) |
| `ingestion` | инфраструктура | Коннекторы к источникам возможностей | M2/M3 | [ingestion.md](../services/ingestion.md) |
| `matching` | приложение | Мэтчинг профиль ↔ возможности | M2 | [matching.md](../services/matching.md) |
| `digest` | приложение | Проактивная ежедневная подборка | M2 | [digest.md](../services/digest.md) |
| `feedback` | приложение | Обучение на реакциях (эмбеддинг-бленд) | M4 | [feedback.md](../services/feedback.md) |
| `drafts` | приложение | Черновики откликов/CFP | M4 | [drafts.md](../services/drafts.md) |
| `scheduler` | инфраструктура | Периодический запуск core loop, дедлайны | M2/M3 | [scheduler.md](../services/scheduler.md) |
| `llm` | инфраструктура | Клиент LLM, промпты, роутинг моделей | M1 | [llm.md](../services/llm.md) |
| `persistence` (db) | инфраструктура | Модели БД, миграции, хранилище | M1 | [persistence.md](../services/persistence.md) |
| `observability` | инфраструктура | Логи, трейсы, учёт токенов/стоимости | M1+ | [observability.md](../services/observability.md) |

## Поток данных (happy path, M2)

```
CV → profile.parse_cv ─┐
ссылки → enrichment ───┴→ profile (+согласие) → (эмбеддинг профиля)
источники → ingestion → opportunity → (эмбеддинг)
                                   ▼
scheduler → matching (сходство + фильтры + ранжирование) → digest
                                   ▼
                       bot (карточки в Telegram)
                                   ▼
              реакции 👍/👎 → feedback → уточнение профиля
```

## Гранизы для будущего выноса в сервисы

Если понадобится масштабирование, первые кандидаты на отдельный сервис:
`ingestion` (много источников, разный rate-limit) и `matching` (CPU/vector-нагрузка).
Границы уже проведены так, чтобы вынос был дешёвым.

## Дорожная карта

Актуальная таблица — в корневом `README.md`.

**Очередь сейчас:** M9 (советник) → M10 (Alembic) → M11 (Mini App).  
M7–M8 ✅.

| Этап | Фокус | Статус |
|------|--------|--------|
| **M7** | Новые источники вакансий (Хабр, Getmatch, TG, career) | ✅ |
| **M8** | Evals подборки / объяснений — `docs/services/evals.md` | ✅ |
| **M9** | Диалог-советник после онбординга | — |
| **M10** | Alembic | — |
| **M11** | Telegram Mini App | — |

**M5** = монитор известных URL. **M6** = discovery (PaperCall → фильтр регион/ниша →
Opportunity). Yaml только bootstrap.

Вне scope: мультиюзер, биллинг, success fee, данные о третьих лицах.
