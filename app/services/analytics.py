"""Product analytics: emit событий в product_events.

Спека: docs/services/analytics.md
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ProductEvent
from app.observability.logging import get_logger

logger = get_logger("kabi.analytics")

EVENT_NAMES = frozenset(
    {
        "onboarding_step_entered",
        "onboarding_step_completed",
        "cv_uploaded",
        "links_added",
        "digest_shown",
        "card_reacted",
        "draft_generated",
        "empty_state",
    }
)


async def emit(
    session: AsyncSession,
    *,
    name: str,
    profile_id: uuid.UUID,
    props: dict[str, Any] | None = None,
) -> None:
    """Пишет product_events в той же транзакции. Никогда не роняет UX-путь."""
    try:
        if name not in EVENT_NAMES:
            logger.warning("analytics_unknown_event name=%s profile=%s", name, profile_id)
            return
        session.add(
            ProductEvent(
                profile_id=profile_id,
                name=name,
                props=dict(props) if props else None,
            )
        )
        await session.flush()
    except Exception:  # noqa: BLE001 — аналитика не должна ломать продукт
        logger.warning(
            "analytics_emit_failed name=%s profile=%s",
            name,
            profile_id,
            exc_info=True,
        )
