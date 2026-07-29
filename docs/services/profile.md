# Модуль: profile

## 1. Назначение
Владелец карьерного профиля пользователя: парсинг CV, хранение и обновление профиля,
подготовка эмбеддинга профиля для мэтчинга. Это «память менеджера о человеке».

## 2. Этап
M1.

## 3. Публичный интерфейс
```python
async def parse_cv(file_path: str) -> ProfileDraft: ...
async def get_profile(user_id: UUID) -> Profile: ...
async def update_profile(user_id: UUID, patch: ProfilePatch) -> Profile: ...
async def compute_embedding(profile: Profile) -> Vector: ...
async def delete_account(session, telegram_id: int) -> DeleteAccountResult: ...
```

### Удаление аккаунта (`delete_account`)

Полный wipe данных пользователя (не путать с «начать заново» — тот только онбординг/ссылки).

Удаляет: `Feedback` → `Match` → `DeadlineReminderLog` → `Profile` → `User`.
`Opportunity` (общие вакансии/CFP) **не** трогаем. Локальный файл CV из `raw_cv_ref`
(если путь внутри `uploads/`) — тоже удаляем.

Критерий: после удаления `/start` ведёт себя как для нового пользователя; `/profile` —
«профиля ещё нет».

## 4. Входы / Выходы
- **Вход:** файл CV (PDF/DOCX); патчи от `dialogue_agent`; обогащение от `enrichment`.
- **Выход:** структурированный `Profile` + эмбеддинг.

## Контракт готовности (`ready_for_matching`)

Профиль считается готовым к мэтчингу (M2), когда заполнены **обязательные** поля.

| Поле | Обязательно | Источник |
|------|-------------|----------|
| `roles` (целевые роли) | да | PARSE / CONFIRM |
| `location` | да | PARSE |
| `work_mode` (remote/hybrid/office) | да | PARSE |
| `salary_expectation` (min + валюта) | **да** | PARSE из CV, иначе ASK |
| `priorities` (job/talk/both) | да (дефолт «оба, вакансии первыми») | ASK |
| `skills` | да | PARSE |
| `enrichment_consent` | да | ASK |
| `speaking_topics` | нет (нужно, если priority включает talk) | INFER/ENRICH |
| `hard_nos` (анти-предпочтения) | нет | ASK — хард-фильтр в мэтчинге |
| `job_search_status` | нет (дефолт «присматриваюсь») | не спрашиваем; в мэтчинге не используется |
| `availability` | нет | не спрашиваем; в мэтчинге не используется |
| `goals` | нет | ASK |

Правило: **без `salary_expectation` профиль не готов** — мэтчинг по вакансиям без вилки
слабый (см. решение по онбордингу в `dialogue-agent.md`). Если ЗП уже в резюме —
шаг зарплаты в онбординге пропускается.

## 5. Зависимости
- **Внутренние:** `app/llm` (извлечение структуры из CV), `app/db`.
- **Внешние:** парсер PDF/DOCX (напр. `pypdf`, `python-docx`).

## 6. Данные
Читает/пишет `Profile`. См. `docs/architecture/data-model.md`.

## 7. Guardrails / ограничения
- Данные только самого пользователя.
- Валидация извлечённых полей (типы, диапазоны зарплаты и т.п.).
- Не терять исходный CV: хранить `raw_cv_ref`.

## 8. Тесты / evals
- **Тест:** парсер извлекает из образца CV ожидаемые поля.
- **Eval:** качество извлечения на нескольких форматах резюме (rubric-scoring).

### Eval-эталон на CV Марины (первый пользователь)
После `parse_cv` в профиле обязаны появиться минимум:
- `roles` ⊇ {Head of Product, Product Lead, CPO};
- `location` = «Москва»; `work_mode` включает remote и office; переезд — нет;
- `skills` ⊇ {Product Management, Product Marketing, Scrum, Agile, A/B-тесты,
  unit-экономика, P&L, SQL}; `languages` ⊇ {русский (родной), английский (свободно)};
- `experience` содержит HeadHunter, Google, МТС (с ролями/периодами);
- НЕ должно быть выдуманных фактов (напр. навыков, которых нет в CV).

## 9. Открытые вопросы
- Хранить исходные CV локально (`/uploads`) или в объектном хранилище?

## 10. Статус
M1: парсинг CV, профиль, готовность, эмбеддинг. Удаление аккаунта: `/delete` →
подтверждение → `delete_account` (cascade личных данных, Opportunity не трогаем).

«Начать заново» ≠ удаление: мягкий сброс онбординга/ссылок, CV-поля остаются.
