"""Тесты расписания рассылок (watch / scheduled / quiet hours)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.schedule import (
    format_schedule,
    is_channel_due,
    is_quiet_hours,
    is_watch_due,
    mark_watch_sent,
    normalize_schedule,
    parse_schedule_command,
    watch_count_today,
)


MSK = ZoneInfo("Europe/Moscow")


def _scheduled(base: dict | None = None) -> dict:
    s = normalize_schedule(base)
    s["delivery"] = "scheduled"
    return s


def test_defaults_watch():
    s = normalize_schedule(None)
    assert s["delivery"] == "watch"
    assert s["rank_mode"] == "fresh_relevant"
    assert s["quiet_hours"] == {"start": 23, "end": 8}
    assert s["watch_daily_limit"] == 10
    assert s["jobs"]["days"] == [0, 1, 2, 3, 4]
    assert s["jobs"]["hour"] == 9
    assert s["talks"]["days"] == [2]
    assert s["talks"]["hour"] == 17


def test_jobs_due_weekday_morning():
    sched = _scheduled()
    now = datetime(2026, 7, 27, 9, 5, tzinfo=MSK)  # Mon
    assert is_channel_due(sched, "jobs", now=now) is True
    assert is_channel_due(sched, "talks", now=now) is False


def test_scheduled_not_due_when_watch():
    sched = normalize_schedule(None)  # delivery=watch
    now = datetime(2026, 7, 27, 9, 5, tzinfo=MSK)
    assert is_channel_due(sched, "jobs", now=now) is False


def test_jobs_not_due_weekend():
    sched = _scheduled()
    now = datetime(2026, 7, 26, 9, 5, tzinfo=MSK)  # Sun
    assert is_channel_due(sched, "jobs", now=now) is False


def test_talks_due_wednesday_evening():
    sched = _scheduled()
    now = datetime(2026, 7, 29, 17, 3, tzinfo=MSK)  # Wed
    assert is_channel_due(sched, "talks", now=now) is True
    assert is_channel_due(sched, "jobs", now=now) is False


def test_idempotent_same_day():
    sched = _scheduled()
    now = datetime(2026, 7, 27, 9, 5, tzinfo=MSK)
    assert (
        is_channel_due(sched, "jobs", last_digest_at={"jobs": "2026-07-27"}, now=now)
        is False
    )


def test_quiet_hours_overnight():
    sched = normalize_schedule(None)
    assert is_quiet_hours(sched, now=datetime(2026, 7, 29, 23, 30, tzinfo=MSK))
    assert is_quiet_hours(sched, now=datetime(2026, 7, 29, 3, 0, tzinfo=MSK))
    assert not is_quiet_hours(sched, now=datetime(2026, 7, 29, 10, 0, tzinfo=MSK))


def test_watch_due_daytime():
    sched = normalize_schedule(None)
    now = datetime(2026, 7, 29, 12, 0, tzinfo=MSK)
    assert is_watch_due(sched, "jobs", now=now) is True


def test_watch_not_due_quiet():
    sched = normalize_schedule(None)
    now = datetime(2026, 7, 29, 23, 30, tzinfo=MSK)
    assert is_watch_due(sched, "jobs", now=now) is False


def test_watch_daily_limit():
    sched = normalize_schedule(None)
    now = datetime(2026, 7, 29, 12, 0, tzinfo=MSK)
    last = mark_watch_sent({}, "jobs", when=now, n_sent=10)
    assert watch_count_today(last, "jobs", day="2026-07-29") == 10
    assert is_watch_due(sched, "jobs", last_digest_at=last, now=now) is False


def test_parse_jobs_weekdays():
    s = parse_schedule_command("вакансии будни 9:00")
    assert s is not None
    assert s["delivery"] == "scheduled"
    assert s["jobs"]["days"] == [0, 1, 2, 3, 4]
    assert s["jobs"]["hour"] == 9
    assert s["jobs"]["minute"] == 0
    assert s["jobs"]["enabled"] is True


def test_parse_talks_wednesday():
    s = parse_schedule_command("выступления среда 17:00")
    assert s is not None
    assert s["talks"]["days"] == [2]
    assert s["talks"]["hour"] == 17
    assert s["delivery"] == "scheduled"


def test_parse_disable():
    s = parse_schedule_command("выступления выкл")
    assert s is not None
    assert s["talks"]["enabled"] is False


def test_parse_watch_and_rank():
    s = parse_schedule_command("мониторинг вкл")
    assert s is not None
    assert s["delivery"] == "watch"
    s2 = parse_schedule_command("режим релевантные", s)
    assert s2 is not None
    assert s2["rank_mode"] == "relevant"
    s3 = parse_schedule_command("режим свежие", s2)
    assert s3 is not None
    assert s3["rank_mode"] == "fresh_relevant"
    s4 = parse_schedule_command("по расписанию", s3)
    assert s4 is not None
    assert s4["delivery"] == "scheduled"


def test_parse_quiet_hours():
    s = parse_schedule_command("тихие часы 22:00-7:00")
    assert s is not None
    assert s["quiet_hours"] == {"start": 22, "end": 7}


def test_onboarding_answers_not_schedule():
    """Кнопки онбординга не должны попасть в парсер расписания."""
    assert parse_schedule_command("Работа") is None
    assert parse_schedule_command("Выступления") is None
    assert parse_schedule_command("Оба") is None
    assert parse_schedule_command("отлично") is None


def test_chat_phrases_not_schedule():
    """Свободный чат про вакансии/выступления без явного времени — не расписание."""
    assert parse_schedule_command("хочу выступления в среду") is None
    assert parse_schedule_command("расскажи про вакансии по пятницам") is None
    assert parse_schedule_command("вакансии будни") is None
    assert parse_schedule_command("выступления среда") is None


def test_parse_enable_toggle():
    s = parse_schedule_command("вакансии вкл")
    assert s is not None
    assert s["jobs"]["enabled"] is True


def test_format_mentions_defaults():
    text = format_schedule(None)
    assert "мониторинг" in text.lower() or "watch" in text.lower()
    assert "свежие" in text.lower()
    assert "23:00" in text
    assert "Вакансии" in text
