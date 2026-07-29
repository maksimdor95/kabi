"""Планировщик core loop и напоминаний. Спека: docs/services/scheduler.md"""

from __future__ import annotations

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.observability.logging import get_logger
from app.scheduler.jobs import deadline_reminders, scheduled_digests

logger = get_logger("kabi.scheduler")


def start_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Рассылки по расписанию профиля (тик 15 мин) + дедлайны 10:00 МСК."""
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(
        scheduled_digests,
        trigger="cron",
        minute="*/15",
        args=[bot],
        id="scheduled_digests",
        replace_existing=True,
    )
    scheduler.add_job(
        deadline_reminders,
        trigger="cron",
        hour=10,
        minute=0,
        args=[bot],
        id="deadline_reminders",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("scheduler_started digests=*/15min deadlines@10:00 Europe/Moscow")
    return scheduler
