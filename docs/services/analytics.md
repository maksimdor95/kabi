# Модуль: analytics (product_events, P1)

## 1. Назначение
Минимальная product-аналитика без Mixpanel: воронка онбординга, impressions
подборок, реакции, черновики, empty-state. Sentry — для ошибок, не для воронки.

## 2. Этап
P1 после Pitch 2.0. Нужна до multi-user scale, чтобы не лететь вслепую.

## 3. Публичный интерфейс

```python
async def emit(
    session,
    *,
    name: str,
    profile_id: UUID,
    props: dict | None = None,
) -> None:
    """Пишет product_events в той же транзакции. Никогда не роняет UX-путь."""

EVENT_NAMES = {
    "onboarding_step_entered",
    "onboarding_step_completed",
    "cv_uploaded",
    "links_added",
    "digest_shown",
    "card_reacted",
    "draft_generated",
    "empty_state",
}
```

## 4. Входы / Выходы
- **Вход:** вызовы из `app/services/*` (и тонко из каналов для empty talks).
- **Выход:** строки `product_events` → SQL/дашборд (P4).

## 5. Зависимости
- **Внутренние:** `app/db.models.ProductEvent`; вызывается из dialogue_agent,
  profile, digest, feedback, drafts.
- **Внешние:** —

## 6. Данные

`product_events`:
| Колонка | Тип | Смысл |
|---------|-----|--------|
| id | UUID | PK |
| profile_id | UUID FK | актор (не telegram_id) |
| name | text | имя события |
| props | jsonb | payload без PII/секретов |
| created_at | timestamptz | |

События и props:

| name | props |
|------|--------|
| onboarding_step_entered | `{step, key}` |
| onboarding_step_completed | `{step, key}` / `{final: true}` |
| cv_uploaded | `{roles_n, skills_n}` |
| links_added | `{n, source: onboarding\|mid\|post}` |
| digest_shown | `{scope, n, match_ids, channel}` |
| card_reacted | `{match_id, reaction, effect, learned}` |
| draft_generated | `{match_id, kind}` |
| empty_state | `{scope, channel}` |

`link_tapped` — вне scope MVP (нужен redirect).

## 7. Guardrails
- Emit **в том же session** до commit; не отдельная транзакция.
- `emit` глотает свои ошибки (лог warning) — аналитика не ломает продукт.
- Не писать в props: токены, initData, полный текст CV/черновика, сырые URL
  с query-секретами.
- Инструментирование в `app/services/*`, не дублировать в bot и api.

## 8. Тесты
- `emit` пишет строку; при сбое session не падает наружу.
- `digest.deliver_feed` при items → digest_shown + shown_at; при [] → empty_state.
- `record_reaction` / `draft_for_match` эмитят card_reacted / draft_generated.

## 9. Открытые вопросы
- Нужен ли TTL/партиционирование таблицы на росте.
- Дашборд SQL — P4.

## 10. Статус
`готово` (P1)
