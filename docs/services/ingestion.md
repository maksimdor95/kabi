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
- **Карточка job:** `normalize_job_draft` перед save — чистый title/org без
  отсечения вакансий; страховка также в `format_card` для старых записей.

## 8. Тесты / evals
- `tests/test_m7_connectors.py` — TG / career / Getmatch / Habr без сети.
- `tests/test_job_card_normalize.py` — кейс «питч в title» (Физикл и др.).
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

- **must (23):** `forproducts`, `productjobgo`, `hireproproduct`, `peersjobboard`,
  `careerfedoroff`, `jobinspb`, `forchiefs`, `nrgjobs`, `HRity`, `yojob`,
  `vacanciesbest`, `hcareers_jobs`, `budujobs`, `pm_jobs`, `digital_jobs`,
  `startupjobs`, `startupfellows`, `careerspace`, `Remoteit`, `remotegeekjob`,
  `remote_w0rk`, `IT_jobs_apply`, `projects_jobs`
- **Не берём:** фриланс (`jobospherechat`, `FreeWorkFeed`), `foranalysts`,
  `uptume`, `studyqa`, боты (`it_lifestyle_bot`).
- **Сеть:** с ВМ `t.me` недоступен без `TG_HTTP_PROXY` (SOCKS5/HTTP EU).
  Коннекторы `tg_connector` и `getmatch_connector` читают `settings.tg_http_proxy`.
  Для Proxy6 обычно нужен `socks5://user:pass@host:port` (не `http://` —
  CONNECT к HTTPS часто timeout).

### Hirify.me — как подключить

Hirify — мета-агрегатор ~900 TG + career sites. **Публичного API/RSS нет.**
В [Terms](https://hirify.me/terms-of-service) прямо запрещены: запросы к
internal API, боты/скрипты, scraping.

Легитимные варианты (по приоритету):

1. **Не дублировать сайт** — поднять TG-прокси и наш каталог 23 каналов:
   большая часть пересекается с источниками Hirify; плюс наши career/HH/SJ.
2. **Официальный фид** — написать `ai@hirify.me` / фаундеру: личный webhook
   или partner API под CPO-фильтр (единственный чистый путь в продукт).
3. **Их Telegram alerts** — на hirify.me Save filter (CPO/HoP) → алерты в TG.
   Дальше: либо читать глазами, либо форвард в свой канал + наш `tg_connector`
   (костыль; не «коннектор Hirify»).
4. **Парсить hirify.me** — нарушает ToS, не делаем.

Отдельный `hirify_connector` в код не кладём, пока нет партнёрского доступа.

### Talks / CFP (не jobs)

- Seed площадок: `talk_places.yaml` → `talk_places_seed`
- Open CFP monitor: `open_cfp` (M5)
- Discovery: `cfp_discovery` (M6)

### Backlog рынка

- Ozon — после antibot.
- Getmatch: публичный search API вместо TG-прокси, если откроют.
- **Hirify.me** — без публичного API (ToS запрещает scrape); путь: партнёрский
  фид или опора на наш TG-каталог после прокси. Не путать с каналом `HRity`.
- Следующие борды (не в коде): Работа.ру, Zarplata.ru, Geekjob, Wellfound / LinkedIn (с оговорками ToS).

## 10. Открытые вопросы
- Ozon — после antibot-решения.
- **TG/Getmatch с ВМ:** задать `TG_HTTP_PROXY` (EU SOCKS5/HTTP) в `.env` на
  стенде; без него каналы в yaml не наполняют БД. Проверка:
  `curl -m 15 -I --proxy "$TG_HTTP_PROXY" https://t.me/s/forproducts` → 200.
- Getmatch: если откроют публичный search API — заменить TG-прокси.
- Hirify.me: только партнёрский фид / webhook; scrape не делаем (ToS).

## 11. Статус
**M7a–d в коде** и в `default_job_connectors()`.
Волна A career JSON (Alfa/WB/Sber/MTS) — `362aed5`, на стенде.
