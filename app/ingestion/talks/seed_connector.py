"""Коннектор возможностей выступить: seed + live CFP.

Каталог data/talk_places.yaml — площадки «куда ходить».
Для conference с cfp_url — живой парсер страницы заявки (дедлайн/статус).
Медиа/подкасты без даты в seed — без дедлайна (evergreen-питч, не CFP).

Спека: docs/services/ingestion.md (этап M3)
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
    return [p for p in places if isinstance(p, dict) and p.get("id") and p.get("name")]


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


def place_to_draft(place: dict[str, Any], *, live: dict[str, Any] | None = None) -> OpportunityDraft:
    kind = place.get("kind") or "media"
    how = place.get("how") or "expert_comment"
    topics = place.get("topics") or []
    topics_s = ", ".join(topics) if topics else "—"
    how_s = _HOW_LABEL.get(how, how)
    kind_s = _KIND_LABEL.get(kind, kind)

    status = (live or {}).get("status") or place.get("status") or "open"
    # Дедлайн только реальный: live CFP или явная дата из seed.
    # Оценочные (deadline_estimated) даты — это догадки, их не показываем как факт.
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

    description = (
        f"Площадка: {kind_s}. Формат: {how_s}. Статус: {status}.\n"
        f"Темы, которые сюда заходят: {topics_s}."
        f"{event_note}{live_note}\n"
        f"Действие: "
        + (
            "подать заявку спикера / следить за следующим CFP."
            if how == "cfp_talk"
            else "подготовить питч в редакцию / продюсеру."
        )
    )

    raw_cfp = place.get("cfp_url")
    # Корень сайта не считаем страницей заявки (иначе «Открыть страницу заявки» врёт).
    cfp_url = raw_cfp if is_actionable_cfp_url(raw_cfp, homepage=place.get("url")) else None
    url = cfp_url or place.get("url")
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
            "cfp_url": cfp_url,
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
                    status = "open" if snap.open is True else ("closed" if snap.open is False else "unknown")
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
