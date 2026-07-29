# Модуль: llm

## 1. Назначение
Единая точка доступа к LLM: клиент, промпты, эмбеддинги и **роутинг моделей**
(мощная для сложного, дешёвая для рутины). Модель — заменяемый «движок» агента.

## Провайдер (решено)
**Yandex Cloud Foundation Models (Yandex AI Studio)** через OpenAI-совместимый API.

- `base_url`: `https://llm.api.cloud.yandex.net/v1`
- Auth: заголовок `Authorization: Api-Key <LLM_API_KEY>`; каталог — в URI модели или заголовке `x-folder-id`.
- Роль ключа: `yc.ai.languageModels.execute` (или `yc.ai.foundationModels.execute`).
- Модели генерации (`gpt://`):
  - primary — `yandexgpt/latest` (диалог, объяснения мэтчинга, черновики);
  - cheap — `yandexgpt-lite/latest` (нормализация, классификация, рутина).
- Эмбеддинги (`emb://`), **размерность 256**, две модели:
  - `text-search-doc/latest` — для возможностей (документов);
  - `text-search-query/latest` — для профиля (запроса).
- Совместимость с OpenAI SDK → можно использовать библиотеку `openai`/`httpx`.

## 2. Этап
M1.

## 3. Публичный интерфейс
```python
async def complete(prompt: Prompt, *, tier: Literal["primary","cheap"]="primary") -> str: ...
async def embed(text: str) -> Vector: ...
# app/llm/prompts/ — версионируемые промпты как часть харнесса
```

## 4. Входы / Выходы
- **Вход:** промпт/текст + желаемый tier модели.
- **Выход:** текст ответа / эмбеддинг.

## 5. Зависимости
- **Внешние:** Yandex AI Studio (OpenAI-compatible HTTP API), провайдер эмбеддингов — TBD.
- **Внутренние:** `app/observability` (учёт токенов/стоимости).
- **Облако:** каталог Yandex Cloud `b1gma918p5t9tlntl2bb` (`drive`), SA `kabi-llm`,
  роль `ai.languageModels.user`, API-ключ со scope `yc.ai.languageModels.execute`.

## 6. Данные
Не владеет доменными сущностями. Промпты хранятся в репозитории (`prompts/`).

## 7. Конфиг (env)
| Переменная | Назначение |
|------------|------------|
| `LLM_API_KEY` | API-ключ SA (не коммитить) |
| `LLM_BASE_URL` | `https://llm.api.cloud.yandex.net/v1` |
| `LLM_FOLDER_ID` | id каталога Yandex Cloud |
| `LLM_MODEL_PRIMARY` | `gpt://<folder-id>/yandexgpt/latest` |
| `LLM_MODEL_CHEAP` | `gpt://<folder-id>/yandexgpt-lite/latest` |
| `LLM_MODEL_EMBED_DOC` | `emb://<folder-id>/text-search-doc/latest` (dim=256) |
| `LLM_MODEL_EMBED_QUERY` | `emb://<folder-id>/text-search-query/latest` (dim=256) |

Клиент — OpenAI-compatible (`Authorization: Api-Key …`). Провайдер сменяемый: меняем env, не интерфейс модуля.
Эмбеддинги: `text-search-doc` для возможностей, `text-search-query` для профиля; обе — 256-мерные.

## 8. Guardrails / ограничения
- Ключи только из env.
- Учёт и лимиты токенов/стоимости; кэш эмбеддингов ради OpEx.
- Промпты версионируются и ревьюятся как код (часть харнесса).

## 9. Тесты / evals
- **Тест:** роутинг выбирает нужный tier по типу задачи.
- **Тест:** кэш эмбеддингов не запрашивает повторно одинаковый текст.

## 10. Открытые вопросы
- ~~Провайдер/модель эмбеддингов~~ — решено: Yandex `text-search-doc`/`text-search-query`, dim=256.
- Суточный лимит токенов/бюджет для контроля OpEx.

## 11. Статус
инфра готова (YC SA + ключ + env); код модуля не начат
