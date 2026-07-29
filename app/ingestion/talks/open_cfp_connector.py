"""M5: коннектор открытых CFP — мониторинг страниц заявок спикера.

Читает data/open_cfp.yaml, для каждого actionable cfp_url тянет страницу
(cfp_live), нормализует в OpportunityDraft(type=talk).

Правила попадания в «живые» возможности:
- open=True → status=open
- open=False → status=closed (в БД для честности, matching отсечёт)
- open=None + будущий deadline → status=open (осторожный допуск)
- open=None без дедлайна → status=unknown (matching трактует как не-closed →
  оставляем, но без дедлайна; /talks не покажет)

Спека: docs/services/ingestion.md (M5)
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from app.ingestion.schemas import OpportunityDraft
from app.ingestion.talks.cfp_live import fetch_cfp_page
from app.ingestion.talks.url_quality import is_actionable_cfp_url
from app.observability.logging import get_logger

logger = get_logger("kabi.ingestion.open_cfp")

_PATH = Path(__file__).resolve().parents[3] / "data" / "open_cfp.yaml"


def load_open_cfp_sources(path: Path | None = None) -> list[dict[str, Any]]:
    seed = path or _PATH
    data = yaml.safe_load(seed.read_text(encoding="utf-8")) or {}
    rows = data.get("sources") or []
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict) and r.get("id") and r.get("name")]


def _status_from_snap(open_flag: bool | None, deadline: datetime | None) -> str:
    if open_flag is True:
        return "open"
    if open_flag is False:
        return "closed"
    now = datetime.now(timezone.utc)
    if deadline is not None:
        dl = deadline if deadline.tzinfo else deadline.replace(tzinfo=timezone.utc)
        if dl >= now:
            return "open"
        return "closed"
    return "unknown"


def source_to_draft(row: dict[str, Any], *, snap) -> OpportunityDraft | None:
    """Собрать draft из yaml + live snapshot. None если URL не actionable / watch_only."""
    if row.get("watch_only"):
        return None
    raw_cfp = row.get("cfp_url")
    homepage = row.get("url")
    if not is_actionable_cfp_url(raw_cfp, homepage=homepage):
        logger.info("open_cfp skip non-actionable id=%s url=%s", row.get("id"), raw_cfp)
        return None

    status = _status_from_snap(snap.open, snap.deadline)
    topics = list(row.get("topics") or [])
    topics_s = ", ".join(topics) if topics else "—"
    note = f"\nСтатус CFP: {snap.note}" if snap.note else ""
    event_note = ""
    if snap.event_start:
        event_note = f"\nСобытие: {snap.event_start.date().isoformat()}"
        if snap.event_end:
            event_note += f" – {snap.event_end.date().isoformat()}"

    description = (
        f"Площадка: конференция. Формат: доклад / CFP (заявка спикера). "
        f"Статус: {status}.{note}{event_note}\n"
        f"Темы, которые сюда заходят: {topics_s}.\n"
        f"Действие: подать заявку спикера."
    )

    return OpportunityDraft(
        type="talk",
        title=f"{row['name']} — доклад / CFP (заявка спикера)",
        org=row["name"],
        description=description,
        location=row.get("location") or "Москва / online",
        remote=True,
        url=raw_cfp,
        source="open_cfp",
        external_id=str(row["id"]),
        deadline=snap.deadline,
        tags=topics,
        meta={
            "kind": "conference",
            "how": "cfp_talk",
            "status": status,
            "topics": topics,
            "cfp_url": raw_cfp,
            "estimated_deadline": False,
            "live_open": snap.open,
            "live_note": snap.note,
        },
    )


class OpenCfpConnector:
    """Живой мониторинг страниц CFP (M5)."""

    source = "open_cfp"

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _PATH

    async def fetch(self, keywords: list[str] | None = None) -> list[OpportunityDraft]:
        del keywords
        rows = load_open_cfp_sources(self.path)
        drafts: list[OpportunityDraft] = []
        for row in rows:
            if row.get("watch_only"):
                logger.info("open_cfp watch_only id=%s", row["id"])
                continue
            cfp_url = row.get("cfp_url")
            if not is_actionable_cfp_url(cfp_url, homepage=row.get("url")):
                continue
            snap = await fetch_cfp_page(str(cfp_url))
            if not snap.raw_ok:
                logger.warning("open_cfp fetch failed id=%s note=%s", row["id"], snap.note)
                continue
            draft = source_to_draft(row, snap=snap)
            if draft is None:
                continue
            drafts.append(draft)
            logger.info(
                "open_cfp id=%s status=%s deadline=%s open=%s",
                row["id"],
                draft.meta.get("status") if draft.meta else None,
                draft.deadline,
                snap.open,
            )
        logger.info("Open CFP: %d черновиков из %d источников", len(drafts), len(rows))
        return drafts
