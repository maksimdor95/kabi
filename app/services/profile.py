"""Владелец профиля: репозиторий, применение черновика CV, готовность, эмбеддинг.

Спека: docs/services/profile.md  (этап M1)
Парсинг CV вынесен в app/services/cv_parser.py.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DeadlineReminderLog, Feedback, Match, Profile, User
from app.domain.profile import ProfileDraft
from app.llm import client as llm
from app.observability.logging import get_logger

logger = get_logger("kabi.profile")

# Обязательные поля для мэтчинга (см. profile.md → контракт готовности).
_REQUIRED_FIELDS = ("roles", "location", "work_mode", "salary_expectation", "skills")
_UPLOADS_DIR = Path("uploads").resolve()


@dataclass(frozen=True)
class DeleteAccountResult:
    deleted: bool
    had_profile: bool
    matches_removed: int = 0
    cv_file_removed: bool = False


async def get_or_create_user(session: AsyncSession, telegram_id: int) -> User:
    user = (
        await session.execute(select(User).where(User.telegram_id == telegram_id))
    ).scalar_one_or_none()
    if user is None:
        user = User(telegram_id=telegram_id)
        session.add(user)
        await session.flush()
    return user


async def get_profile(session: AsyncSession, user_id: uuid.UUID) -> Profile | None:
    return (
        await session.execute(select(Profile).where(Profile.user_id == user_id))
    ).scalar_one_or_none()


def _unlink_cv_if_local(raw_cv_ref: str | None) -> bool:
    """Удалить локальный CV только из uploads/ (не чужие пути)."""
    if not raw_cv_ref:
        return False
    try:
        path = Path(raw_cv_ref).resolve()
    except OSError:
        return False
    if _UPLOADS_DIR not in path.parents and path.parent != _UPLOADS_DIR:
        return False
    if not path.is_file():
        return False
    try:
        path.unlink()
        return True
    except OSError as exc:
        logger.warning("cv_unlink_failed path=%s err=%s", path, exc)
        return False


async def delete_account(session: AsyncSession, telegram_id: int) -> DeleteAccountResult:
    """Полностью удалить пользователя и связанные личные данные.

    Opportunity не трогаем. См. docs/services/profile.md → delete_account.
    """
    user = (
        await session.execute(select(User).where(User.telegram_id == telegram_id))
    ).scalar_one_or_none()
    if user is None:
        return DeleteAccountResult(deleted=False, had_profile=False)

    user_id = user.id
    profile = await get_profile(session, user_id)
    matches_removed = 0
    cv_removed = False

    if profile is not None:
        cv_removed = _unlink_cv_if_local(profile.raw_cv_ref)
        match_ids = list(
            (
                await session.execute(select(Match.id).where(Match.profile_id == profile.id))
            ).scalars().all()
        )
        if match_ids:
            await session.execute(delete(Feedback).where(Feedback.match_id.in_(match_ids)))
            matches_removed = len(match_ids)
        await session.execute(delete(Match).where(Match.profile_id == profile.id))
        await session.execute(
            delete(DeadlineReminderLog).where(DeadlineReminderLog.profile_id == profile.id)
        )
        await session.delete(profile)

    await session.delete(user)
    await session.flush()

    from app.services import dialog_memory

    await dialog_memory.clear(user_id)

    logger.info(
        "account_deleted tg=%s had_profile=%s matches=%s cv=%s",
        telegram_id,
        profile is not None,
        matches_removed,
        cv_removed,
    )
    return DeleteAccountResult(
        deleted=True,
        had_profile=profile is not None,
        matches_removed=matches_removed,
        cv_file_removed=cv_removed,
    )


async def apply_cv_draft(
    session: AsyncSession,
    user_id: uuid.UUID,
    draft: ProfileDraft,
    raw_cv_ref: str | None = None,
) -> Profile:
    """Создать/обновить профиль полями из черновика CV."""
    profile = await get_profile(session, user_id)
    if profile is None:
        profile = Profile(user_id=user_id)
        session.add(profile)

    profile.roles = draft.roles
    profile.skills = draft.skills
    profile.location = draft.location
    profile.languages = draft.languages
    profile.work_mode = draft.work_mode
    profile.experience = draft.experience
    # Всегда заменяем: иначе темы/цели с чужого LinkedIn остаются после нового CV.
    profile.speaking_topics = list(draft.speaking_topics or [])
    profile.goals = draft.goals
    # Зарплата из CV (или None → спросим на онбординге)
    profile.salary_expectation = draft.salary_expectation
    if raw_cv_ref:
        profile.raw_cv_ref = raw_cv_ref

    refresh_readiness(profile)
    await session.flush()
    return profile


async def update_profile(
    session: AsyncSession, profile: Profile, patch: dict
) -> Profile:
    """Применить патч (из онбординга/обогащения) и пересчитать готовность."""
    for key, value in patch.items():
        if hasattr(profile, key):
            setattr(profile, key, value)
    refresh_readiness(profile)
    await session.flush()
    return profile


def refresh_readiness(profile: Profile) -> None:
    """Выставить ready_for_matching по контракту готовности."""
    ready = all(bool(getattr(profile, f)) for f in _REQUIRED_FIELDS)
    profile.ready_for_matching = ready and bool(profile.enrichment_consent)


def profile_to_text(profile: Profile) -> str:
    """Текстовое представление профиля для эмбеддинга."""
    parts = [
        " ".join(profile.roles or []),
        " ".join(profile.skills or []),
        profile.location or "",
        profile.work_mode or "",
        " ".join(profile.speaking_topics or []),
        profile.goals or "",
    ]
    return "\n".join(p for p in parts if p).strip()


def format_profile_card(profile: Profile) -> str:
    """Человекочитаемая сводка профиля для /profile."""
    lines: list[str] = ["<b>Твой профиль у менеджера</b>"]

    if profile.roles:
        lines.append("• Роли: " + ", ".join(profile.roles))
    if profile.location:
        lines.append("• Локация: " + profile.location)
    if profile.work_mode:
        lines.append("• Формат: " + profile.work_mode)
    if profile.skills:
        lines.append("• Навыки: " + ", ".join(profile.skills[:15]))
        if len(profile.skills) > 15:
            lines.append(f"  …ещё {len(profile.skills) - 15}")
    if profile.languages:
        lines.append("• Языки: " + ", ".join(profile.languages))
    if profile.speaking_topics:
        lines.append("• Темы выступлений/экспертности: " + ", ".join(profile.speaking_topics[:12]))
    if profile.goals:
        lines.append("• Цели: " + profile.goals)

    sal = profile.salary_expectation or {}
    if isinstance(sal, dict) and sal.get("min"):
        lines.append(f"• Зарплата от: {sal['min']:,} {sal.get('currency') or 'RUB'}".replace(",", " "))

    prio = {"job": "работа", "talk": "выступления", "both": "работа и выступления"}
    lines.append("• Приоритет: " + prio.get(profile.priorities or "both", profile.priorities or "оба"))

    hard = profile.hard_nos or {}
    if hard.get("raw"):
        lines.append("• Красные флаги: " + str(hard["raw"]))
    elif hard:
        lines.append("• Красные флаги: есть")

    links = list((profile.source_links or {}).get("links") or [])
    if links:
        lines.append("• Источники:")
        for link in links[:8]:
            lines.append(f"  — {link}")

    ready = "да ✅" if profile.ready_for_matching else "ещё нет"
    lines.append(f"• Готов к подбору: {ready}")
    lines.append("")
    lines.append("Команды: /today · /pitch · /talks · /saved · /profile · /schedule")
    lines.append("Обновить резюме — пришли PDF. Ссылки — просто кинь в чат.")
    lines.append("Удалить всё — /delete")
    return "\n".join(lines)


async def compute_embedding(session: AsyncSession, profile: Profile) -> None:
    """Посчитать и сохранить эмбеддинг профиля (kind=query)."""
    text = profile_to_text(profile)
    if not text:
        return
    profile.embedding = await llm.embed(text, kind="query")
    await session.flush()
