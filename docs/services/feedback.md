# Модуль: feedback

## 1. Назначение
Замыкает цикл обучения: реакции пользователя (👍/👎/скрыть/сохранить) уточняют
профиль и будущий мэтчинг. «Менеджер учится на предпочтениях звезды».

## 2. Этап
M2 (запись реакций) + M4 (обучение через эмбеддинг).

## 3. Публичный интерфейс
```python
def blend_embedding(base, delta, *, sign: int, alpha: float) -> list[float]: ...
async def record_reaction(session, match_id: str, reaction: str) -> ReactionResult: ...
async def list_saved(session, profile) -> list[DigestItem]: ...
```
Реакции: `up` | `down` | `hide` | `save` | `unsave`.
`save` на уже `saved` — toggle (снять с избранного).

Обучение (M4): на `up`/`down` сдвигаем `Profile.embedding`:
- up: `normalize(emb + 0.15 * opp_emb)`
- down: `normalize(emb - 0.20 * opp_emb)`
`save`/`hide`/`unsave` эмбеддинг не трогают. `ReactionResult.learned` — удалось ли сдвинуть.

## 4. Входы / Выходы
- **Вход:** события нажатий кнопок из `bot` (`fb:<action>:<match_id>`).
- **Выход:** записи `Feedback`; обновление `Match.status`; при 👍/👎 — обновление `Profile.embedding`.

## 5. Зависимости
- **Внутренние:** `app/db`, `app/services/digest` (DigestItem), `app/services/profile.compute_embedding`.
- **Внешние:** —

## 6. Данные
Пишет `Feedback`, обновляет `Match.status` (`liked`/`disliked`/`hidden`/`saved`/`new`),
при обучении — `Profile.embedding`.

## 7. Guardrails / ограничения
- Малый alpha (0.15 / 0.20) — сглаживание, без резких скачков на одной реакции.
- Прозрачность: ack «учёл для следующих подборок» при `learned=True`.
- Повторный `compute_embedding` (новое CV) сбрасывает сдвиги — ок для MVP.

## 8. Тесты / evals
- **Тест:** save → unsave (toggle) корректно меняет статус матча.
- **Тест:** blend — 👍 повышает cosine к opp_emb, 👎 понижает (синтетические векторы).
- **Eval:** после серии 👎 похожие вакансии реже в топе `/today`.

## 9. Открытые вопросы
- —

## 10. Статус
M2+M4: запись реакций, избранное, снятие; онлайн-бленд эмбеддинга на 👍/👎.
