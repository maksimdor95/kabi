# Модель данных (черновик)

> Единый источник правды по сущностям. Реализация — `app/db/models.py` (SQLAlchemy).
> Меняешь сущность — обновляешь этот файл в том же PR.

## Сущности

### User
Пользователь Telegram. В MVP — один.

| Поле | Тип | Заметки |
|------|-----|---------|
| id | UUID | PK |
| telegram_id | bigint | уникальный |
| created_at | timestamptz | |

### Profile
Карьерный профиль пользователя (то, что «знает менеджер»).

| Поле | Тип | Заметки |
|------|-----|---------|
| id | UUID | PK |
| user_id | UUID | FK → User |
| skills | text[] | навыки |
| experience | jsonb | список мест/ролей |
| roles | text[] | желаемые роли |
| location | text | |
| languages | text[] | |
| salary_expectation | jsonb | {min, comfortable, currency}; **обязательно для мэтчинга** |
| work_mode | text | remote / hybrid / office |
| speaking_topics | text[] | темы для выступлений |
| priorities | text | `job` \| `talk` \| `both`; дефолт `both` (вакансии первыми) |
| job_search_status | text | `active` \| `passive` \| `top_only`; дефолт `passive` |
| hard_nos | jsonb | анти-предпочтения: индустрии/тип продукта/размер компании |
| availability | jsonb | занятость сейчас, срок выхода (недели) |
| goals | text | карьерные цели |
| enrichment_consent | bool | согласие обогащать профиль из публичных источников |
| source_links | jsonb | ссылки пользователя (HH/LinkedIn/выступления/сайт) |
| raw_cv_ref | text | ссылка на исходный CV-файл |
| embedding | vector(256) | эмбеддинг профиля (pgvector) |
| ready_for_matching | bool | вычисляемый флаг готовности (см. profile.md) |
| onboarding_step | int | указатель текущего шага онбординга (см. dialogue-agent.md) |
| digest_schedule | jsonb | расписание/режим доставки digests (M6b) |
| last_digest_at | jsonb | идемпотентность слотов рассылки |
| updated_at | timestamptz | |

### Opportunity
Возможность (вакансия или выступление), нормализованная из источника.

| Поле | Тип | Заметки |
|------|-----|---------|
| id | UUID | PK |
| type | text | `job` \| `talk` |
| title | text | |
| org | text | компания/организатор |
| description | text | |
| location | text | |
| remote | bool | |
| salary | jsonb | если есть |
| deadline | timestamptz | для CFP (M3) |
| url | text | первоисточник |
| source | text | идентификатор коннектора |
| external_id | text | id в источнике (дедуп на уровне ingestion) |
| meta | jsonb | служебные поля коннектора (cfp_url, how, …) |
| embedding | vector(256) | эмбеддинг возможности |
| fetched_at | timestamptz | |

### Match
Результат мэтчинга профиля и возможности.

| Поле | Тип | Заметки |
|------|-----|---------|
| id | UUID | PK |
| profile_id | UUID | FK → Profile |
| opportunity_id | UUID | FK → Opportunity |
| score | float | релевантность |
| reason | text | объяснение «почему подходит» (LLM) |
| status | text | `new` \| `liked` \| `hidden` \| `applied` |
| created_at | timestamptz | |

### Feedback
Реакция пользователя на матч — топливо для обучения (M4).

| Поле | Тип | Заметки |
|------|-----|---------|
| id | UUID | PK |
| match_id | UUID | FK → Match |
| reaction | text | `up` \| `down` \| `hide` \| `save` |
| created_at | timestamptz | |

### ProductEvent (P1)
Product-аналитика без Mixpanel. Спека: `docs/services/analytics.md`.

| Поле | Тип | Заметки |
|------|-----|---------|
| id | UUID | PK |
| profile_id | UUID | FK → Profile |
| name | text | имя события |
| props | jsonb | без PII/секретов |
| created_at | timestamptz | |

## Связи

```
User 1──1 Profile 1──* Match *──1 Opportunity
              │          │
              │          1──* Feedback
              └──* ProductEvent
```

Удаление аккаунта (`/delete`): Feedback → Match → DeadlineReminderLog →
ProductEvent → Profile → User.
Opportunity не удаляется (общая база).

## Заметки по индексам

- `Opportunity (source, external_id)` — уникальный индекс **план** (сейчас дедуп в
  `ingestion`); добавлять миграцией после аудита дублей на стенде.
- Векторные поля `embedding` — **размерность 256** (Yandex `text-search-*`). Тип `vector(256)`.
- Векторные индексы (ivfflat/hnsw) на `Profile.embedding` и `Opportunity.embedding` — позже.
- `Match (profile_id, status)` — индексы есть.
- Схема версионируется Alembic (`alembic/versions/`, baseline `20260813_0001`).
