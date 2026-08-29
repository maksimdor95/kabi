# Модуль: pitch (Pitch 2.0)

## 1. Назначение
Сделать поток `/pitch` (СМИ / подкасты / community) полезным как у
менеджера: не «ссылка на главную + обрезанный reason», а **формат входа**,
**конкретный угол** и **actionable next step**. Конференции с CFP — в
`/talks` / `open_cfp`, сюда не смешиваем.

## 2. Этап дорожной карты
P0 после M11. Итерации: (1) данные + карточка + порог качества;
(2) shown / org-cooldown / org-penalty; (3) evals `pitch_v1`.

## 3. Публичный интерфейс

```python
# seed → Opportunity
place_to_draft(place) -> OpportunityDraft  # meta: how, pitch_url, how_to, actionable, …

# карточка (presentation-neutral)
card_approach(item) -> str | None   # блок «Как зайти»
reason_snippet(text, *, limit=REASON_LIMIT_PITCH)  # для talk — 480

# витрина / анти-спам
list_pending(..., scope="pitch") -> list[DigestItem]
deliver_feed(session, profile, items, *, scope="pitch", channel) -> list[DigestItem]
blocked_pitch_orgs(session, profile_id) -> set[str]  # cooldown + penalty
```

## 4. Входы / Выходы
- **Вход:** `data/talk_places.yaml` (+ live CFP только для `how=cfp_talk`);
  профиль (`speaking_topics`, roles, skills).
- **Выход:** `Opportunity(type=talk, evergreen)` → Match → карточка бота / Mini App
  с блоками «Как зайти» + «Почему ты» + CTA.

## 5. Зависимости
- **Внутренние:** `ingestion/talks`, `matching`, `digest`, `cards`, `feedback`,
  `bot/keyboards`, `app/api`, `web/`.
- **Внешние:** —

## 6. Данные

Поля seed (поверх старых `id/name/kind/how/url/topics`):

| Поле | Смысл |
|------|--------|
| `pitch_url` | Страница подачи / tips / форма (не homepage) |
| `how_to` | 1–3 предложения: как зайти |
| `example_topics` | Примеры углов, которые сюда заходят |
| `contact_hint` | Куда писать (редакция@… / «форма на сайте»), без выдумок |

`Opportunity.meta`: `kind`, `how`, `topics`, `pitch_url`, `how_to`,
`example_topics`, `contact_hint`, `cfp_url`, `actionable` (bool), `status`.

`Match.shown_at` (timestamptz, nullable) — факт доставки в UI/чат, не факт
создания строки.

## 7. Guardrails / ограничения
- Без `actionable` (нет `pitch_url`/`cfp_url`/`how_to`) — **не в топ** `/pitch`.
- Не выдумывать дедлайны у evergreen.
- CTA: приоритет `cfp_url` → `pitch_url` → иначе URL скрыт / secondary, primary —
  «Черновик питча».
- Org cooldown: та же `org` не в топе 30 дней после `shown_at`.
- Org penalty: после 👎/🙈 по talk этой org — 90 дней вне топа.
- «Почему ты» для talk: лимит 480 символов (2–3 предложения), не 220.

## 8. Тесты / evals
- Seed: `vc` имеет `pitch_url` ≠ homepage; `actionable=True` в meta.
- `card_approach` не пустой при `how_to` в meta.
- Matching pitch: opp без `actionable` не попадает в candidates.
- `deliver_feed` пишет `shown_at` (+ digest_shown); повторный rank уважает org cooldown.
- Eval (фаза 3): пул `evals/matching/…/pitch_v1` — reason без угла / шаблонный =
  fail.

## 9. Открытые вопросы
- Нужен ли отдельный «каталог на потом» в UI для non-actionable, или просто
  не показывать.
- Повторный `/pitch` с «идеей угла по сохранённым» — итерация 2b.

## 10. Статус
`готов` — итерации 1–2 (сид, карточка, порог качества, shown_at, org cooldown/penalty).
Осталось: evals `pitch_v1`, «идея угла по сохранённым» при пустом /pitch.
