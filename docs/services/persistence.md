# Модуль: persistence (app/db)

## 1. Назначение
Хранилище и модели данных: SQLAlchemy-модели, сессии БД, миграции, репозитории.
Это «долговременная память» агента.

## 2. Этап
M1 (модели/сессии) ✅; **M10** — Alembic вместо `create_all` + ручных `ALTER`.

## 3. Публичный интерфейс
```python
# app/db/models.py   — ORM-модели
# app/db/session.py  — async engine + session factory + init_db()
# app/db/migrate.py  — ensure_schema / upgrade_head / stamp_head
# scripts/migrate.py — CLI
```

## 4. Входы / Выходы
- **Вход:** доменные объекты для сохранения; запросы.
- **Выход:** сохранённые/прочитанные сущности.

## 5. Зависимости
- **Внешние:** PostgreSQL + pgvector, SQLAlchemy, asyncpg, Alembic.

## 6. Данные
Владеет всеми сущностями из `docs/architecture/data-model.md`.

## 7. Guardrails / ограничения
- Домен (`app/domain`) не зависит от этого модуля (зависимость направлена внутрь).
- Схема меняется **только** миграциями в `alembic/versions/`.
- Секреты БД — из env (`.env`), не в `alembic.ini`.
- На существующей БД без `alembic_version` (после старого `create_all`) —
  `ensure_schema` делает `stamp head`, данные не трогает.

## 8. Тесты / evals
- Unit: `tests/test_migrations.py` (baseline файл, stamp vs upgrade).
- Ручной smoke: `PYTHONPATH=. python scripts/migrate.py ensure` на локальной/стендовой БД.

## 9. Открытые вопросы
- Уникальный индекс `(source, external_id)` в спеке data-model есть, в ORM пока
  дедуп на уровне ingestion — отдельная миграция после аудита дублей.
- Векторные индексы (HNSW/IVFFlat) — по мере роста пула.

## 10. Статус
**M10 ✅:** Alembic baseline `20260813_0001`, `init_db` → `ensure_schema`,
деплой гоняет `scripts/migrate.py ensure` до restart бота.

### Команды
```bash
PYTHONPATH=. python scripts/migrate.py ensure   # штатно
PYTHONPATH=. python scripts/migrate.py upgrade
PYTHONPATH=. alembic upgrade head
PYTHONPATH=. alembic revision --autogenerate -m "msg"  # новые изменения
```
