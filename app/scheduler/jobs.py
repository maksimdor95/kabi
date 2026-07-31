"""Периодические задачи: рассылки (watch / scheduled) + дедлайны.

Спека: docs/services/scheduler.md
"""

from __future__ import annotations

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select

from app.db.models import Profile, User
from app.db.session import get_session
from app.observability.logging import get_logger
from app.services import deadlines as deadlines_service
from app.services import digest as digest_service
from app.services import schedule as schedule_service
from app.services.matching import MatchScope
from bot.keyboards import card_keyboard, format_card, main_menu_keyboard, menu_for_profile

logger = get_logger("kabi.scheduler")

# Свежесть для watch: не тащить старый пул как «только что появилось».
_WATCH_MAX_AGE_HOURS = 72.0

_CHANNEL_META: dict[str, tuple[MatchScope, str, dict]] = {
    "jobs": (
        "jobs",
        "Вакансии — {n}:",
        {"include_talks": False, "live_cfp": False},
    ),
    "talks": (
        "talks",
        "Выступления — {n}:",
        {"include_talks": True, "live_cfp": True},
    ),
}


async def _send_channel(
    bot: Bot,
    *,
    profile: Profile,
    telegram_id: int,
    channel: str,
    delivery: str,
) -> int:
    """Собрать и отправить канал. Возвращает число отправленных карточек (−1 при ошибке)."""
    scope, intro_tmpl, ingest_kw = _CHANNEL_META[channel]
    sched = schedule_service.normalize_schedule(profile.digest_schedule)
    limit = 7
    max_age: float | None = None
    live_cfp = bool(ingest_kw.get("live_cfp"))
    if delivery == "watch":
        limit = int(sched["watch_batch_limit"])
        max_age = _WATCH_MAX_AGE_HOURS
        # Watch-тик talks: без тяжёлого live CFP каждые 15 мин.
        if channel == "talks":
            live_cfp = False

    async with get_session() as session:
        prof = await session.get(Profile, profile.id)
        if prof is None or not prof.ready_for_matching:
            return -1
        try:
            items = await digest_service.build_digest(
                session,
                prof,
                scope=scope,
                do_ingest=True,
                include_talks=bool(ingest_kw.get("include_talks")),
                live_cfp=live_cfp,
                limit=limit,
                max_age_hours=max_age,
            )
        except Exception as exc:
            logger.warning("digest %s failed tg=%s: %s", channel, telegram_id, exc)
            return -1

        local = schedule_service.now_local(
            schedule_service.normalize_schedule(prof.digest_schedule)
        )
        if delivery == "scheduled":
            # Пустая пачка тоже помечается — не долбить слот весь день.
            prof.last_digest_at = schedule_service.mark_sent(
                prof.last_digest_at, channel, when=local  # type: ignore[arg-type]
            )
        elif items:
            prof.last_digest_at = schedule_service.mark_watch_sent(
                prof.last_digest_at,
                channel,  # type: ignore[arg-type]
                when=local,
                n_sent=len(items),
            )
        await session.commit()
        prio = prof.priorities

    if not items:
        logger.info("%s %s tg=%s: empty", delivery, channel, telegram_id)
        return 0

    intro = intro_tmpl.format(n=len(items))
    if delivery == "watch":
        intro = ("Новое по мониторингу — {n}:" if channel == "jobs" else "Новые площадки — {n}:").format(
            n=len(items)
        )

    try:
        await bot.send_message(
            telegram_id,
            intro,
            reply_markup=main_menu_keyboard(prio),
        )
        for item in items:
            await bot.send_message(
                telegram_id,
                format_card(item),
                reply_markup=card_keyboard(item.match_id),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
    except TelegramAPIError as exc:
        logger.warning("send %s failed tg=%s: %s", channel, telegram_id, exc)
        return -1
    return len(items)


async def scheduled_digests(bot: Bot) -> None:
    """Тик каждые 15 мин: watch или слот scheduled — с учётом priorities."""
    async with get_session() as session:
        rows = (
            await session.execute(
                select(Profile, User.telegram_id)
                .join(User, User.id == Profile.user_id)
                .where(Profile.ready_for_matching.is_(True))
            )
        ).all()

    for profile, telegram_id in rows:
        sched = schedule_service.normalize_schedule(profile.digest_schedule)
        last = dict(profile.last_digest_at or {})
        delivery = sched["delivery"]
        prio = (profile.priorities or "both").lower()
        channels: list[str] = []
        if prio in ("job", "both"):
            channels.append("jobs")
        if prio in ("talk", "both"):
            channels.append("talks")

        for channel in channels:
            if delivery == "watch":
                due = schedule_service.is_watch_due(
                    sched, channel, last_digest_at=last  # type: ignore[arg-type]
                )
            else:
                due = schedule_service.is_channel_due(
                    sched, channel, last_digest_at=last  # type: ignore[arg-type]
                )
            if not due:
                continue
            logger.info(
                "digest due delivery=%s channel=%s prio=%s tg=%s",
                delivery,
                channel,
                prio,
                telegram_id,
            )
            n = await _send_channel(
                bot,
                profile=profile,
                telegram_id=telegram_id,
                channel=channel,
                delivery=delivery,
            )
            if n < 0:
                continue
            local = schedule_service.now_local(sched)
            if delivery == "scheduled":
                last[channel] = local.date().isoformat()
            elif n > 0:
                last = schedule_service.mark_watch_sent(
                    last, channel, when=local, n_sent=n  # type: ignore[arg-type]
                )


async def deadline_reminders(bot: Bot) -> None:
    """Напоминания о дедлайнах (окна 14/7/3/1 день), без дублей."""
    async with get_session() as session:
        users = (
            await session.execute(
                select(Profile, User.telegram_id)
                .join(User, User.id == Profile.user_id)
                .where(
                    Profile.ready_for_matching.is_(True),
                    Profile.priorities.in_(("talk", "both")),
                )
            )
        ).all()
        if not users:
            return

        for profile, telegram_id in users:
            try:
                due = await deadlines_service.due_reminders_for_profile(session, profile)
            except Exception as exc:
                logger.warning("deadline query failed tg=%s: %s", telegram_id, exc)
                continue
            if not due:
                continue

            lines = ["⏰ Напоминание о дедлайнах:"]
            for item, window in due:
                dl = item.deadline.strftime("%d.%m.%Y")
                left = "сегодня" if item.days_left == 0 else f"через {item.days_left} дн."
                url = f"\n  {item.url}" if item.url else ""
                lines.append(f"• {item.title} — до {dl} ({left}){url}")
                await deadlines_service.mark_reminded(
                    session, profile.id, item.opportunity_id, window
                )
            await session.commit()

            try:
                await bot.send_message(
                    telegram_id,
                    "\n".join(lines),
                    disable_web_page_preview=True,
                    reply_markup=menu_for_profile(profile),
                )
            except TelegramAPIError as exc:
                logger.warning("deadline remind failed tg=%s: %s", telegram_id, exc)


# Совместимость со старым именем job id.
daily_pipeline = scheduled_digests
