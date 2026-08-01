# Модуль: ingestion

## 1. Назначение
Коннекторы к источникам возможностей. Забирают сырые данные, нормализуют в единую
модель `Opportunity`, дедуплицируют. Это «инструменты», которыми агент ищет мир.

## 2. Этап
M2 (вакансии API), M3 (seed talks), M5 (монитор URL), M6 (discovery CFP),
**M7** (TG + career sites + Getmatch + Habr HTML).

## 3. Публичный интерфейс
```python
class JobConnector(Protocol):
    source: str
    async def fetch(keywords, *, area=None) -> list[OpportunityDraft]: ...

# M2: hh_connector, superjob_connector
# M3–M6: talks seed / open_cfp / discovery
# M7a: tg_connector + data/tg_job_channels.yaml
# M7b: getmatch_connector (TG g_jobchannel → getmatch.ru/vacancies/{id})
# M7c: career_sites_connector + data/career_sites.yaml
#      yandex_api | alfa_api | wb_api | sber_api | mts_api | html_list
# M7d: habr_connector (RSS + HTML vacancy-card)
```
Коннектор возвращает `OpportunityDraft`; runner маппит в ORM, дедуп, эмбеддинги.
Теги draft → `meta.topics` (не дописываются в description как «Темы: …»).

## 4. Входы / Выходы
- **Вход:** внешние API/RSS/страницы; ключевые слова из профиля.
- **Выход:** нормализованные `Opportunity`.

## 5. Зависимости
- **Внутренние:** `app/db`, `app/observability`, `app/llm` (embed в runner).
- **Внешние:** `httpx`, YAML-каталоги в `data/`.

## 6. Данные
Пишет `Opportunity`. Дедуп по `(source, external_id)`.

## 7. Guardrails / ограничения
- Только публичные источники; никакого сбора данных о третьих лицах.
- Секреты не в yaml / не в репо.
- Rate-limit / backoff; падение одного коннектора не роняет runner.
- **Хабр:** официальный API плохо стыкуется с proactive cache — HTML/RSS
  осознанный ToS-риск (зафиксировано продуктом).
- **Getmatch:** веб-API за логином / SPA без SSR → публичный канал
  `t.me/s/g_jobchannel` + обогащение страницы вакансии.
- **TG:** публичные каналы через `t.me/s/` без админ-прав.
  Короткий HTTP timeout (~8s): с части облаков `t.me` висит долго.
- **Runner jobs:** сохранение после **каждого** коннектора — медленный scrape
  не блокирует уже полученные HH/SJ (иначе `/today` пустой, пока TG таймаутит).

## 8. Тесты / evals
- `tests/test_m7_connectors.py` — TG / career / Getmatch / Habr без сети.
- Eval-пул после M7: `evals/matching/pools/jobs_m7_v2.jsonl` (HH + M7 sources).

## 9. Карта источников (актуально)

Профиль MVP: **Head of Product / CPO**, Москва, senior.

### Коннекторы (`default_job_connectors`)

| # | Коннектор | Source id | Статус |
|---|-----------|-----------|--------|
| 1 | HeadHunter API | `hh.ru` | ✅ |
| 2 | SuperJob API | `superjob.ru` | ✅ |
| 3 | Telegram job channels | `tg_<channel>` | ✅ |
| 4 | Career sites (см. ниже) | `career_*` | ✅ |
| 5 | Getmatch (via `g_jobchannel`) | `getmatch.ru` | ✅ |
| 6 | Хабр Карьера RSS/HTML | `career.habr.com` | ✅ |

### Career sites (`data/career_sites.yaml`)

| Компания | Kind | Source | Статус |
|----------|------|--------|--------|
| Яндекс | `yandex_api` | `career_yandex` | ✅ |
| Сбер | `sber_api` | `career_sber` | ✅ (волна A / Leo) |
| Альфа-Банк | `alfa_api` | `career_alfa` | ✅ (волна A / Leo) |
| Wildberries | `wb_api` | `career_wb` | ✅ (волна A / Leo) |
| МТС | `mts_api` | `career_mts` | ✅ (волна A / Leo) |
| Авито | `html_list` | `career_avito` | ✅ |
| VK | `html_list` | `career_vk` | ✅ |
| Т-Банк | `html_list` | `career_tbank` | ✅ |
| Ozon | `html_list` | — | ❌ antibot |

### Telegram (`data/tg_job_channels.yaml`)

- **must (7):** `forproducts`, `forchiefs`, `nrgjobs`, `HRity`, `yojob`, `vacanciesbest`, `peersjobboard`
- **optional (3):** `pm_jobs`, `digital_jobs`, `startupjobs`

### Talks / CFP (не jobs)

- Seed площадок: `talk_places.yaml` → `talk_places_seed`
- Open CFP monitor: `open_cfp` (M5)
- Discovery: `cfp_discovery` (M6)

### Backlog рынка

- Ozon — после antibot.
- Getmatch: публичный search API вместо TG-прокси, если откроют.
- Следующие борды (не в коде): Работа.ру, Zarplata.ru, Geekjob, Wellfound / LinkedIn (с оговорками ToS).

## 10. Открытые вопросы
- Ozon — после antibot-решения.
- Getmatch: если откроют публичный search API — заменить TG-прокси.

## 11. Статус
**M7a–d в коде** и в `default_job_connectors()`.
Волна A career JSON (Alfa/WB/Sber/MTS) — `362aed5`, на стенде.
