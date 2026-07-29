"""Расписание рассылок: доставка (watch/scheduled) + отбор + слоты.

Дефолт: мониторинг (watch) + fresh_relevant + тихие часы 23:00–08:00.
Спека: docs/services/scheduler.md
"""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

Channel = Literal["jobs", "talks"]
Delivery = Literal["watch", "scheduled"]
RankMode = Literal["fresh_relevant", "relevant"]

_DAY_NAMES = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
_DAY_ALIASES = {
    "пн": 0,
    "понедельник": 0,
    "вт": 1,
    "вторник": 1,
    "ср": 2,
    "среда": 2,
    "среду": 2,
    "чт": 3,
    "четверг": 3,
    "пт": 4,
    "пятница": 4,
    "пятницу": 4,
    "сб": 5,
    "суббота": 5,
    "вс": 6,
    "воскресенье": 6,
}
_WEEKDAYS = [0, 1, 2, 3, 4]

DEFAULT_SCHEDULE: dict[str, Any] = {
    "timezone": "Europe/Moscow",
    "delivery": "watch",
    "rank_mode": "fresh_relevant",
    "quiet_hours": {"start": 23, "end": 8},
    "watch_daily_limit": 10,
    "watch_batch_limit": 3,
    "jobs": {"enabled": True, "days": list(_WEEKDAYS), "hour": 9, "minute": 0},
    "talks": {"enabled": True, "days": [2], "hour": 17, "minute": 0},
}

_TIME_RE = re.compile(r"(\d{1,2})[:.\s](\d{2})")
_QUIET_RANGE_RE = re.compile(
    r"(\d{1,2})(?::(\d{2}))?\s*[-–—]\s*(\d{1,2})(?::(\d{2}))?"
)


def default_schedule() -> dict[str, Any]:
    return deepcopy(DEFAULT_SCHEDULE)


def normalize_schedule(raw: dict | None) -> dict[str, Any]:
    base = default_schedule()
    if not isinstance(raw, dict):
        return base
    tz = str(raw.get("timezone") or base["timezone"])
    base["timezone"] = tz

    delivery = str(raw.get("delivery") or base["delivery"]).lower()
    base["delivery"] = "scheduled" if delivery == "scheduled" else "watch"

    rank = str(raw.get("rank_mode") or raw.get("mode") or base["rank_mode"]).lower()
    if rank in ("relevant", "relevance", "релевантн"):
        base["rank_mode"] = "relevant"
    else:
        base["rank_mode"] = "fresh_relevant"

    qh = raw.get("quiet_hours") if isinstance(raw.get("quiet_hours"), dict) else {}
    start = int(qh.get("start", base["quiet_hours"]["start"]))
    end = int(qh.get("end", base["quiet_hours"]["end"]))
    base["quiet_hours"] = {
        "start": max(0, min(23, start)),
        "end": max(0, min(23, end)),
    }

    try:
        base["watch_daily_limit"] = max(1, min(50, int(raw.get("watch_daily_limit", 10))))
    except (TypeError, ValueError):
        base["watch_daily_limit"] = 10
    try:
        base["watch_batch_limit"] = max(1, min(10, int(raw.get("watch_batch_limit", 3))))
    except (TypeError, ValueError):
        base["watch_batch_limit"] = 3

    for ch in ("jobs", "talks"):
        src = raw.get(ch) if isinstance(raw.get(ch), dict) else {}
        days = src.get("days", base[ch]["days"])
        if isinstance(days, list):
            days = sorted({int(d) for d in days if str(d).isdigit() or isinstance(d, int)})
            days = [d for d in days if 0 <= d <= 6]
        if not days:
            days = list(base[ch]["days"])
        hour = int(src.get("hour", base[ch]["hour"]))
        minute = int(src.get("minute", base[ch]["minute"]))
        base[ch] = {
            "enabled": bool(src.get("enabled", base[ch]["enabled"])),
            "days": days,
            "hour": max(0, min(23, hour)),
            "minute": max(0, min(59, minute)),
        }
    return base


def _tz(schedule: dict[str, Any]) -> ZoneInfo:
    try:
        return ZoneInfo(schedule.get("timezone") or "Europe/Moscow")
    except Exception:
        return ZoneInfo("Europe/Moscow")


def now_local(schedule: dict[str, Any], *, now: datetime | None = None) -> datetime:
    tz = _tz(schedule)
    if now is None:
        return datetime.now(tz)
    if now.tzinfo is None:
        return now.replace(tzinfo=tz)
    return now.astimezone(tz)


def is_quiet_hours(
    schedule: dict[str, Any],
    *,
    now: datetime | None = None,
) -> bool:
    """Тихие часы: [start, 24) ∪ [0, end). Если start==end — тихих нет."""
    sched = normalize_schedule(schedule)
    qh = sched["quiet_hours"]
    start, end = int(qh["start"]), int(qh["end"])
    if start == end:
        return False
    local = now_local(sched, now=now)
    h = local.hour
    if start > end:
        return h >= start or h < end
    return start <= h < end


def is_channel_due(
    schedule: dict[str, Any],
    channel: Channel,
    *,
    last_digest_at: dict | None = None,
    now: datetime | None = None,
    window_minutes: int = 15,
) -> bool:
    """Пора ли слот scheduled: день + окно минут + ещё не слали сегодня."""
    sched = normalize_schedule(schedule)
    if sched["delivery"] != "scheduled":
        return False
    rule = sched[channel]
    if not rule.get("enabled"):
        return False
    local = now_local(sched, now=now)
    if local.weekday() not in rule["days"]:
        return False
    target = rule["hour"] * 60 + rule["minute"]
    current = local.hour * 60 + local.minute
    if not (target <= current < target + window_minutes):
        return False
    today = local.date().isoformat()
    sent = (last_digest_at or {}).get(channel)
    if sent == today:
        return False
    return True


def watch_count_today(
    last_digest_at: dict | None,
    channel: Channel,
    *,
    day: str,
) -> int:
    last = last_digest_at or {}
    if last.get(f"{channel}_watch_day") != day:
        return 0
    try:
        return max(0, int(last.get(f"{channel}_watch_count") or 0))
    except (TypeError, ValueError):
        return 0


def is_watch_due(
    schedule: dict[str, Any],
    channel: Channel,
    *,
    last_digest_at: dict | None = None,
    now: datetime | None = None,
) -> bool:
    """Тик watch: канал вкл, не тихие часы, дневной лимит не исчерпан."""
    sched = normalize_schedule(schedule)
    if sched["delivery"] != "watch":
        return False
    if not sched[channel].get("enabled"):
        return False
    if is_quiet_hours(sched, now=now):
        return False
    local = now_local(sched, now=now)
    day = local.date().isoformat()
    used = watch_count_today(last_digest_at, channel, day=day)
    return used < int(sched["watch_daily_limit"])


def mark_sent(last_digest_at: dict | None, channel: Channel, *, when: datetime) -> dict:
    out = dict(last_digest_at or {})
    out[channel] = when.date().isoformat()
    return out


def mark_watch_sent(
    last_digest_at: dict | None,
    channel: Channel,
    *,
    when: datetime,
    n_sent: int,
) -> dict:
    """Учесть отправленные в watch карточки (пустую пачку не трогаем снаружи)."""
    out = dict(last_digest_at or {})
    day = when.date().isoformat()
    prev = watch_count_today(out, channel, day=day)
    out[f"{channel}_watch_day"] = day
    out[f"{channel}_watch_count"] = prev + max(0, n_sent)
    return out


def _fmt_days(days: list[int]) -> str:
    if days == _WEEKDAYS:
        return "будни"
    if days == [0, 1, 2, 3, 4, 5, 6]:
        return "каждый день"
    return ", ".join(_DAY_NAMES[d] for d in days)


def _fmt_rank(mode: str) -> str:
    return "свежие+релевантные" if mode == "fresh_relevant" else "только релевантные"


def format_schedule(schedule: dict | None) -> str:
    s = normalize_schedule(schedule)
    qh = s["quiet_hours"]
    delivery = s["delivery"]
    lines = [
        "📅 Рассылки",
        f"Часовой пояс: {s['timezone']}",
        "",
    ]
    if delivery == "watch":
        lines.append("Доставка: мониторинг (watch)")
        lines.append(
            f"Тихие часы: {qh['start']:02d}:00–{qh['end']:02d}:00"
        )
        lines.append(
            f"Лимит: до {s['watch_daily_limit']} карточек/день "
            f"(пачка до {s['watch_batch_limit']})"
        )
    else:
        lines.append("Доставка: по расписанию")
    lines.append(f"Отбор: {_fmt_rank(s['rank_mode'])}")
    lines.append("")

    for ch, title in (("jobs", "Вакансии"), ("talks", "Выступления")):
        rule = s[ch]
        if not rule["enabled"]:
            lines.append(f"• {title}: выкл")
            continue
        t = f"{rule['hour']:02d}:{rule['minute']:02d}"
        if delivery == "scheduled":
            lines.append(f"• {title}: {_fmt_days(rule['days'])} в {t}")
        else:
            lines.append(f"• {title}: вкл (слот запасной {_fmt_days(rule['days'])} {t})")

    lines.extend(
        [
            "",
            "Изменить, например:",
            "• мониторинг вкл",
            "• по расписанию",
            "• вакансии будни 9:00",
            "• выступления среда 17:00",
            "• режим свежие / режим релевантные",
            "• тихие часы 23:00-8:00",
            "• выступления выкл",
        ]
    )
    return "\n".join(lines)


def _parse_global_delivery(raw: str, sched: dict[str, Any]) -> dict[str, Any] | None:
    """Команды без канала: мониторинг / по расписанию / тихие часы / режим отбора."""
    if any(
        w in raw
        for w in (
            "мониторинг",
            "watch",
            "режим мониторинг",
            "доставка мониторинг",
        )
    ) and not any(w in raw for w in ("выкл", "отключ", "стоп", "off")):
        # «мониторинг» / «мониторинг вкл»
        if "расписан" in raw and "мониторинг" not in raw:
            return None
        sched["delivery"] = "watch"
        return sched

    if any(
        w in raw
        for w in (
            "по расписанию",
            "режим расписание",
            "доставка расписание",
            "scheduled",
        )
    ):
        sched["delivery"] = "scheduled"
        return sched

    if "тихие" in raw or "quiet" in raw:
        m = _QUIET_RANGE_RE.search(raw)
        if not m:
            return None
        start = int(m.group(1)) % 24
        end = int(m.group(3)) % 24
        sched["quiet_hours"] = {"start": start, "end": end}
        return sched

    if "режим" in raw or "отбор" in raw:
        if any(w in raw for w in ("релевант", "relevant", "точн")):
            sched["rank_mode"] = "relevant"
            return sched
        if any(w in raw for w in ("свеж", "нов", "fresh")):
            sched["rank_mode"] = "fresh_relevant"
            return sched

    return None


def parse_schedule_command(text: str, current: dict | None = None) -> dict[str, Any] | None:
    """Разобрать фразу настройки. None — не похоже на команду расписания.

    Не перехватывает ответы онбординга вроде «Работа» / «Выступления» / «Оба».
    """
    raw = (text or "").strip().lower()
    if not raw:
        return None

    if raw in {"работа", "выступления", "оба", "пропустить"}:
        return None

    sched = normalize_schedule(current)

    global_hit = _parse_global_delivery(raw, sched)
    # Глобальные фразы без канала — ок. Если есть канал+время — ниже тоже обработаем.
    jobs_ch = any(w in raw for w in ("ваканси", "jobs"))
    talks_ch = any(w in raw for w in ("выступлен", "питч", "talks", "cfp"))
    if not jobs_ch and "работ" in raw and any(
        w in raw for w in ("расписан", "будн", "кажд", "вкл", "выкл", ":")
    ):
        jobs_ch = True

    if not jobs_ch and not talks_ch:
        return global_hit

    if jobs_ch:
        channel: Channel = "jobs"
    else:
        channel = "talks"

    has_time = bool(_TIME_RE.search(raw) or re.search(r"\bв\s+\d{1,2}\b", raw))
    has_days = (
        "будн" in raw
        or "будний" in raw
        or "рабоч" in raw
        or "каждый день" in raw
        or "ежеднев" in raw
        or any(a in raw for a in _DAY_ALIASES)
    )
    has_toggle = any(
        w in raw for w in ("выкл", "отключ", "стоп", "disable", "off", "вкл", "включи", "enable", "on")
    )
    has_schedule_word = "расписан" in raw
    has_rank = ("режим" in raw or "отбор" in raw) and any(
        w in raw for w in ("свеж", "нов", "fresh", "релевант", "relevant", "точн")
    )

    # Канал + только режим отбора
    if has_rank and not (has_time or has_toggle or has_schedule_word or has_days):
        if any(w in raw for w in ("релевант", "relevant", "точн")):
            sched["rank_mode"] = "relevant"
        else:
            sched["rank_mode"] = "fresh_relevant"
        return sched

    if not (has_time or has_toggle or has_schedule_word):
        # «вакансии мониторинг» → watch + канал
        if global_hit is not None:
            return global_hit
        return None

    rule = dict(sched[channel])

    if any(w in raw for w in ("выкл", "отключ", "стоп", "disable", "off")):
        rule["enabled"] = False
        sched[channel] = rule
        return sched
    if has_toggle and not has_time and not has_days:
        rule["enabled"] = True
        sched[channel] = rule
        return sched

    rule["enabled"] = True

    if "будн" in raw or "будний" in raw or "рабоч" in raw:
        rule["days"] = list(_WEEKDAYS)
    elif "каждый день" in raw or "ежеднев" in raw:
        rule["days"] = [0, 1, 2, 3, 4, 5, 6]
    else:
        found_days = []
        for alias, num in _DAY_ALIASES.items():
            if alias in raw:
                found_days.append(num)
        if found_days:
            rule["days"] = sorted(set(found_days))

    tm = _TIME_RE.search(raw)
    if tm:
        rule["hour"] = int(tm.group(1)) % 24
        rule["minute"] = int(tm.group(2)) % 60
    else:
        hm = re.search(r"\bв\s+(\d{1,2})\b", raw)
        if hm:
            rule["hour"] = int(hm.group(1)) % 24
            rule["minute"] = 0

    sched[channel] = rule
    # Явное время/дни канала → спокойный режим слотов
    if has_time or has_days or has_schedule_word:
        sched["delivery"] = "scheduled"
    return sched
