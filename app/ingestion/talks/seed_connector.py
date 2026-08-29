"""Коннектор возможностей выступить: seed + live CFP.

Каталог data/talk_places.yaml — площадки «куда ходить».
Для conference с cfp_url — живой парсер страницы заявки (дедлайн/статус).
Медиа/подкасты без даты в seed — без дедлайна (evergreen-питч, не CFP).

Pitch 2.0: pitch_url / how_to / example_topics / contact_hint → meta + CTA.
Спека: docs/services/pitch.md, docs/services/ingestion.md (M3).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from app.ingestion.schemas import OpportunityDraft
from app.ingestion.talks.cfp_live import fetch_cfp_page
from app.ingestion.talks.url_quality import is_actionable_cfp_url
from app.observability.logging import get_logger

logger = get_logger("kabi.ingestion.talks")

_SEED_PATH = Path(__file__).resolve().parents[3] / "data" / "talk_places.yaml"

_HOW_LABEL = {
    "expert_comment": "экспертный комментарий / цитата",
    "column": "колонка / авторский материал",
    "interview": "интервью",
    "podcast_guest": "гость подкаста / эфира",
    "cfp_talk": "доклад / CFP (заявка спикера)",
    "workshop": "воркшоп / мастер-класс",
}

_KIND_LABEL = {
    "media": "СМИ",
    "podcast": "подкаст / видео",
    "tv": "ТВ",
    "conference": "конференция",
    "community": "отраслевая площадка",
}


def load_places(path: Path | None = None) -> list[dict[str, Any]]:
    seed = path or _SEED_PATH
    data = yaml.safe_load(seed.read_text(encoding="utf-8")) or {}
    places = data.get("places") or []
    if not isinstance(places, list):
        return []
    return [
        p
        for p in places
        if isinstance(p, dict)
        and p.get("id")
        and p.get("name")
        and p.get("enabled", True) is not False
    ]


def _parse_deadline(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return datetime(raw.year, raw.month, raw.day, 23, 59, tzinfo=timezone.utc)
    if isinstance(raw, (int, float)):
        return None
    text = str(raw).strip()[:10]
    try:
        d = date.fromisoformat(text)
        return datetime(d.year, d.month, d.day, 23, 59, tzinfo=timezone.utc)
    except ValueError:
        return None


def _str_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if x and str(x).strip()]


def _clean_url(raw: Any) -> str | None:
    if not raw or not isinstance(raw, str):
        return None
    url = raw.strip()
    return url or None


def is_actionable_place(place: dict[str, Any]) -> bool:
    """Есть следующий шаг: форма/tips URL или явная инструкция how_to."""
    if is_actionable_cfp_url(place.get("cfp_url"), homepage=place.get("url")):
        return True
    pitch = _clean_url(place.get("pitch_url"))
    if pitch and is_actionable_cfp_url(pitch, homepage=place.get("url")):
        return True
    how_to = (place.get("how_to") or "").strip()
    return len(how_to) >= 40


def place_to_draft(place: dict[str, Any], *, live: dict[str, Any] | None = None) -> OpportunityDraft:
    kind = place.get("kind") or "media"
    how = place.get("how") or "expert_comment"
    topics = _str_list(place.get("topics"))
    example_topics = _str_list(place.get("example_topics"))
    how_to = (place.get("how_to") or "").strip() or None
    contact_hint = (place.get("contact_hint") or "").strip() or None
    how_s = _HOW_LABEL.get(how, how)
    kind_s = _KIND_LABEL.get(kind, kind)

    status = (live or {}).get("status") or place.get("status") or "open"
    seed_deadline = (
        None if place.get("deadline_estimated") else _parse_deadline(place.get("deadline"))
    )
    deadline = (live or {}).get("deadline") or seed_deadline

    event_note = ""
    if place.get("event_start"):
        event_note = f"\nСобытие: {place.get('event_start')}"
        if place.get("event_end"):
            event_note += f" – {place.get('event_end')}"
    if live and live.get("event_start"):
        event_note = f"\nСобытие (с сайта): {live['event_start']}"
        if live.get("event_end"):
            event_note += f" – {live['event_end']}"

    live_note = ""
    if live and live.get("note"):
        live_note = f"\nСтатус CFP: {live['note']}"

    topics_s = ", ".join(topics) if topics else "—"
    examples_s = ", ".join(example_topics) if example_topics else ""

    lines = [
        f"Площадка: {kind_s}. Формат: {how_s}. Статус: {status}.",
        f"Темы, которые сюда заходят: {topics_s}.",
    ]
    if examples_s:
        lines.append(f"Примеры углов: {examples_s}.")
    if how_to:
        lines.append(f"Как зайти: {how_to}")
    if contact_hint:
        lines.append(f"Контакт: {contact_hint}")
    if event_note:
        lines.append(event_note.strip())
    if live_note:
        lines.append(live_note.strip())
    if how == "cfp_talk" and not how_to:
        lines.append("Действие: подать заявку спикера / следить за следующим CFP.")
    description = "\n".join(lines)

    raw_cfp = place.get("cfp_url")
    cfp_url = raw_cfp if is_actionable_cfp_url(raw_cfp, homepage=place.get("url")) else None
    raw_pitch = _clean_url(place.get("pitch_url"))
    pitch_url = (
        raw_pitch
        if raw_pitch and is_actionable_cfp_url(raw_pitch, homepage=place.get("url"))
        else None
    )
    url = cfp_url or pitch_url or place.get("url")
    actionable = is_actionable_place(place) or bool(cfp_url)

    return OpportunityDraft(
        type="talk",
        title=f"{place['name']} — {how_s}",
        org=place["name"],
        description=description,
        location=place.get("location")
        or ("online" if kind in {"podcast", "media", "community"} else "Москва / online"),
        remote=kind in {"podcast", "media", "community", "tv"},
        url=url,
        source="talk_places_seed",
        external_id=str(place["id"]),
        deadline=deadline,
        tags=list(topics),
        meta={
            "kind": kind,
            "how": how,
            "status": status,
            "topics": list(topics),
            "example_topics": example_topics,
            "how_to": how_to,
            "contact_hint": contact_hint,
            "cfp_url": cfp_url,
            "pitch_url": pitch_url,
            "actionable": actionable,
            "estimated_deadline": bool(place.get("deadline_estimated")),
        },
    )


class TalkPlacesConnector:
    """Seed + optional live CFP refresh."""

    source = "talk_places_seed"

    def __init__(self, path: Path | None = None, *, live_cfp: bool = True) -> None:
        self.path = path or _SEED_PATH
        self.live_cfp = live_cfp

    async def fetch(self, keywords: list[str] | None = None) -> list[OpportunityDraft]:
        del keywords
        places = load_places(self.path)
        drafts: list[OpportunityDraft] = []
        for place in places:
            live_meta: dict[str, Any] | None = None
            raw_cfp = place.get("cfp_url")
            cfp_url = (
                raw_cfp
                if is_actionable_cfp_url(raw_cfp, homepage=place.get("url"))
                else None
            )
            if self.live_cfp and cfp_url and place.get("how") == "cfp_talk":
                snap = await fetch_cfp_page(cfp_url)
                if snap.raw_ok:
                    status = (
                        "open"
                        if snap.open is True
                        else ("closed" if snap.open is False else "unknown")
                    )
                    live_meta = {
                        "status": status,
                        "deadline": snap.deadline or _parse_deadline(place.get("deadline")),
                        "event_start": snap.event_start.date().isoformat()
                        if snap.event_start
                        else place.get("event_start"),
                        "event_end": snap.event_end.date().isoformat()
                        if snap.event_end
                        else place.get("event_end"),
                        "note": snap.note,
                    }
                    logger.info(
                        "cfp_live id=%s status=%s deadline=%s",
                        place["id"],
                        status,
                        live_meta.get("deadline"),
                    )
            drafts.append(place_to_draft(place, live=live_meta))
        logger.info("Talk places: %d площадок (live_cfp=%s)", len(drafts), self.live_cfp)
        return drafts
