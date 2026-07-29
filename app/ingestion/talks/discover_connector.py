"""M6: коннектор discovery CFP — PaperCall (+ позже другие сигналы).

Результат: OpportunityDraft(source=cfp_discovery). Пользователь ничего не вводит.
"""

from __future__ import annotations

from app.ingestion.schemas import OpportunityDraft
from app.ingestion.talks.discovery_filters import profile_niche_keywords
from app.ingestion.talks.papercall_discover import PapercallEvent, fetch_open_cfps
from app.observability.logging import get_logger

logger = get_logger("kabi.ingestion.cfp_discovery")


def event_to_draft(ev: PapercallEvent) -> OpportunityDraft:
    status = "open" if ev.open is not False else "closed"
    topics = list(ev.topics or [])
    topics_s = ", ".join(topics) if topics else "—"
    event_note = ""
    if ev.event_start:
        event_note = f"\nСобытие: {ev.event_start.date().isoformat()}"
    description = (
        f"Площадка: конференция (найдено через PaperCall). "
        f"Формат: доклад / CFP (заявка спикера). Статус: {status}.{event_note}\n"
        f"Темы, которые сюда заходят: {topics_s}.\n"
        f"Локация: {ev.location or '—'}.\n"
        f"Действие: подать заявку спикера."
    )
    return OpportunityDraft(
        type="talk",
        title=f"{ev.name} — доклад / CFP (заявка спикера)",
        org=ev.name,
        description=description,
        location=ev.location or "online",
        remote="online" in (ev.location or "").lower()
        or "remote" in (ev.location or "").lower()
        or not ev.location,
        url=ev.cfp_url,
        source="cfp_discovery",
        external_id=f"papercall-{ev.slug}",
        deadline=ev.deadline,
        tags=topics,
        meta={
            "kind": "conference",
            "how": "cfp_talk",
            "status": status,
            "topics": topics,
            "cfp_url": ev.cfp_url,
            "estimated_deadline": False,
            "discovered_via": "papercall",
            "live_open": ev.open,
        },
    )


class CfpDiscoveryConnector:
    """Автообнаружение открытых CFP (M6)."""

    source = "cfp_discovery"

    def __init__(
        self,
        *,
        niche_keywords: list[str] | None = None,
        limit: int = 15,
    ) -> None:
        self.niche_keywords = niche_keywords
        self.limit = limit

    async def fetch(self, keywords: list[str] | None = None) -> list[OpportunityDraft]:
        # keywords из профиля (роли) — доп. ниша
        niche = list(self.niche_keywords or profile_niche_keywords())
        if keywords:
            niche = profile_niche_keywords(roles=list(keywords))
        events = await fetch_open_cfps(niche_keywords=niche, limit=self.limit)
        drafts = [event_to_draft(ev) for ev in events]
        logger.info("cfp_discovery: %d открытых CFP", len(drafts))
        return drafts
