"""Дедлайны talk/CFP: выборка и идемпотентные напоминания (M3)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DeadlineReminderLog, Opportunity, Profile
from app.observability.logging import get_logger

logger = get_logger("kabi.deadlines")

DEADLINE_WINDOWS_DAYS = (14, 7, 3, 1)


@dataclass
class DeadlineItem:
    opportunity_id: str
    title: str
    org: str | None
    url: str | None
    deadline: datetime
    days_left: int


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def list_upcoming(
    session: AsyncSession,
    *,
    within_days: int = 60,
    limit: int = 20,
) -> list[DeadlineItem]:
    """Ближайшие реальные дедлайны talk/CFP (без evergreen-СМИ без даты)."""
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=within_days)
    rows = (
        await session.execute(
            select(Opportunity)
            .where(
                and_(
                    Opportunity.type == "talk",
                    Opportunity.deadline.is_not(None),
                    Opportunity.deadline >= now,
                    Opportunity.deadline <= horizon,
                )
            )
            .order_by(Opportunity.deadline.asc())
            .limit(limit)
        )
    ).scalars().all()

    items: list[DeadlineItem] = []
    for opp in rows:
        dl = _as_utc(opp.deadline)  # type: ignore[arg-type]
        days = max(0, (dl.date() - now.date()).days)
        items.append(
            DeadlineItem(
                opportunity_id=str(opp.id),
                title=opp.title,
                org=opp.org,
                url=opp.url,
                deadline=dl,
                days_left=days,
            )
        )
    return items


def _window_for_days_left(days_left: int) -> int | None:
    """Какое окно сработало (14/7/3/1), если days_left попал в него."""
    for w in DEADLINE_WINDOWS_DAYS:
        if days_left == w:
            return w
    # также в день дедлайна
    if days_left == 0:
        return 1
    return None


async def due_reminders_for_profile(
    session: AsyncSession,
    profile: Profile,
    *,
    within_days: int = 14,
) -> list[tuple[DeadlineItem, int]]:
    """Пары (item, window_days) которым ещё не слали напоминание."""
    items = await list_upcoming(session, within_days=within_days, limit=50)
    due: list[tuple[DeadlineItem, int]] = []
    for item in items:
        window = _window_for_days_left(item.days_left)
        if window is None:
            continue
        already = (
            await session.execute(
                select(DeadlineReminderLog.id).where(
                    DeadlineReminderLog.profile_id == profile.id,
                    DeadlineReminderLog.opportunity_id == uuid.UUID(item.opportunity_id),
                    DeadlineReminderLog.window_days == window,
                )
            )
        ).scalar_one_or_none()
        if already:
            continue
        due.append((item, window))
    return due


async def mark_reminded(
    session: AsyncSession,
    profile_id,
    opportunity_id: str,
    window_days: int,
) -> None:
    session.add(
        DeadlineReminderLog(
            profile_id=profile_id,
            opportunity_id=uuid.UUID(opportunity_id),
            window_days=window_days,
        )
    )
    await session.flush()


def format_deadlines_message(items: list[DeadlineItem]) -> str:
    if not items:
        return (
            "🎤 Конференции с датой подачи заявки\n\n"
            "Сейчас нет площадок с известным сроком подачи.\n"
            "Вакансии — /today, СМИ и подкасты — /pitch."
        )
    lines = [
        "🎤 Конференции — ближайшие сроки подачи заявки спикера:",
        "",
    ]
    for it in items:
        dl = it.deadline.strftime("%d.%m.%Y")
        left = "сегодня" if it.days_left == 0 else f"через {it.days_left} дн."
        url = f"\n  {it.url}" if it.url else ""
        lines.append(f"• {it.title} — до {dl} ({left}){url}")
    return "\n".join(lines)
