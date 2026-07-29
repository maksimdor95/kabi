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
| external_id | text | id в источнике (дедуп) |
| embedding | vector | эмбеддинг возможности |
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

## Связи

```
User 1──1 Profile 1──* Match *──1 Opportunity
                         │
                         1──* Feedback
```

Удаление аккаунта (`/delete`): Feedback → Match → DeadlineReminderLog → Profile → User.
Opportunity не удаляется (общая база).

## Заметки по индексам

- `Opportunity (source, external_id)` — уникальный, для дедупликации.
- Векторные поля `embedding` — **размерность 256** (Yandex `text-search-*`). Тип `vector(256)`.
- Векторные индексы (ivfflat/hnsw) на `Profile.embedding` и `Opportunity.embedding`.
- `Match (profile_id, status)` — для быстрой сборки ежедневной подборки.
