"""HTTP-ручки Mini App. Спека: docs/services/miniapp.md §4.

Слой транспорта: разобрать запрос → вызвать сервис → отдать DTO.
Решения о том, «что правильно», принимает `app/services/*`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Actor, current_profile, db_session, rate_limit_expensive
from app.api.schemas import (
    CardOut,
    ConfigOut,
    DraftOut,
    FeedOut,
    MeOut,
    ReactionIn,
    ReactionOut,
    Scope,
)
from app.config import settings
from app.db.models import Match
from app.observability.logging import get_logger
from app.services import cards
from app.services import digest as digest_service
from app.services import drafts as drafts_service
from app.services import feedback as feedback_service
from app.services.digest import DigestItem
from app.services.onboarding import STEPS

router = APIRouter(prefix="/api/v1")
logger = get_logger("kabi.api")

_FEED_LIMIT_DEFAULT = 12
_FEED_LIMIT_MAX = 30


def _card(item: DigestItem, *, saved: bool = False) -> CardOut:
    title, org = cards.card_title(item)
    is_talk = item.opp_type == "talk"
    return CardOut(
        match_id=item.match_id,
        type="talk" if is_talk else "job",
        title=title,
        org=org,
        location=item.location,
        remote=item.remote,
        salary=cards.format_salary(item.salary),
        score=round(item.score, 4),
        reason=cards.card_reason(item),
        summary=cards.card_summary(item, title=title),
        approach=cards.card_approach(item),
        how=item.how,
        url=item.url,
        link_label=item.link_label,
        source=cards.format_source_label(item.source),
        deadline=item.deadline,
        saved=saved,
        draft_primary=is_talk and (item.hide_url or not item.link_label),
    )


def _not_ready() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "profile_not_ready",
            "message": "Профиль ещё не готов к подбору. Допиши ответы в чате с ботом.",
        },
    )


@router.get("/config", response_model=ConfigOut)
async def get_config() -> ConfigOut:
    """Публичный конфиг: фронт понимает, куда он попал. Секретов здесь нет."""
    return ConfigOut(app_env=settings.app_env, scopes=["jobs", "pitch", "talks"])


@router.get("/me", response_model=MeOut)
async def get_me(
    actor: Actor = Depends(current_profile),
    session: AsyncSession = Depends(db_session),
) -> MeOut:
    profile = actor.owned_profile

    saved_count = (
        await session.execute(
            select(func.count())
            .select_from(Match)
            .where(Match.profile_id == profile.id, Match.status == "saved")
        )
    ).scalar_one()

    step = profile.onboarding_step or 0
    question = STEPS[step].question if 0 <= step < len(STEPS) else None
    salary = profile.salary_expectation if isinstance(profile.salary_expectation, dict) else {}
    hard = profile.hard_nos if isinstance(profile.hard_nos, dict) else {}

    return MeOut(
        telegram_id=actor.telegram_id,
        display_name=actor.init_data.user.display_name,
        roles=list(profile.roles or []),
        skills=list(profile.skills or []),
        location=profile.location,
        work_mode=profile.work_mode,
        languages=list(profile.languages or []),
        speaking_topics=list(profile.speaking_topics or []),
        goals=profile.goals,
        salary_min=salary.get("min"),
        salary_currency=salary.get("currency") or ("RUB" if salary.get("min") else None),
        priorities=profile.priorities or "both",
        hard_nos=hard.get("raw") if isinstance(hard.get("raw"), str) else None,
        source_links=list((profile.source_links or {}).get("links") or []),
        ready_for_matching=bool(profile.ready_for_matching),
        onboarding_step=step,
        onboarding_question=None if profile.ready_for_matching else question,
        saved_count=int(saved_count),
        updated_at=profile.updated_at,
    )


async def _build_feed(
    session: AsyncSession,
    actor: Actor,
    *,
    scope: Scope,
    limit: int,
    do_ingest: bool,
) -> FeedOut:
    profile = actor.owned_profile
    if not profile.ready_for_matching:
        raise _not_ready()

    if do_ingest:
        # Добираем свежие Match, если ещё есть несматченные кандидаты.
        # Даже при items=0 ниже покажем уже существующие status=new.
        await digest_service.build_digest(
            session,
            profile,
            scope=scope,
            do_ingest=True,
            limit=limit,
        )

    items = await digest_service.list_pending(
        session,
        profile,
        scope=scope,
        limit=limit,
    )
    await digest_service.deliver_feed(
        session, profile, items, scope=scope, channel="miniapp"
    )
    logger.info(
        "miniapp_feed tg=%s scope=%s ingest=%s items=%s",
        actor.telegram_id,
        scope,
        do_ingest,
        len(items),
    )
    return FeedOut(scope=scope, items=[_card(i) for i in items], refreshed=do_ingest)


@router.get("/feed", response_model=FeedOut)
async def get_feed(
    scope: Scope = Query("jobs"),
    limit: int = Query(_FEED_LIMIT_DEFAULT, ge=1, le=_FEED_LIMIT_MAX),
    actor: Actor = Depends(current_profile),
    session: AsyncSession = Depends(db_session),
) -> FeedOut:
    """Подборка из уже собранных данных: открытие приложения должно быть мгновенным."""
    return await _build_feed(session, actor, scope=scope, limit=limit, do_ingest=False)


@router.post("/feed/refresh", response_model=FeedOut)
async def refresh_feed(
    scope: Scope = Query("jobs"),
    limit: int = Query(_FEED_LIMIT_DEFAULT, ge=1, le=_FEED_LIMIT_MAX),
    actor: Actor = Depends(rate_limit_expensive),
    session: AsyncSession = Depends(db_session),
) -> FeedOut:
    """То же, но со сходом в источники (долго — вызывается по кнопке)."""
    return await _build_feed(session, actor, scope=scope, limit=limit, do_ingest=True)


@router.get("/saved", response_model=list[CardOut])
async def get_saved(
    actor: Actor = Depends(current_profile),
    session: AsyncSession = Depends(db_session),
) -> list[CardOut]:
    items = await feedback_service.list_saved(
        session, actor.owned_profile, channel="miniapp"
    )
    return [_card(i, saved=True) for i in items]


@router.post("/matches/{match_id}/reaction", response_model=ReactionOut)
async def post_reaction(
    match_id: str,
    payload: ReactionIn,
    actor: Actor = Depends(current_profile),
    session: AsyncSession = Depends(db_session),
) -> ReactionOut:
    result = await feedback_service.record_reaction(
        session,
        match_id,
        payload.reaction,
        actor_profile_id=actor.owned_profile.id,
    )
    if not result.ok:
        if result.effect == "forbidden":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "forbidden", "message": "Это не твоя карточка."},
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "Карточка устарела."},
        )
    return ReactionOut(ok=True, effect=result.effect, learned=result.learned)


@router.post("/matches/{match_id}/draft", response_model=DraftOut)
async def post_draft(
    match_id: str,
    actor: Actor = Depends(rate_limit_expensive),
    session: AsyncSession = Depends(db_session),
) -> DraftOut:
    try:
        result = await drafts_service.draft_for_match(session, actor.owned_profile, match_id)
    except Exception as exc:  # noqa: BLE001 — наружу отдаём аккуратный 502, детали в лог
        logger.exception("miniapp_draft_failed match=%s", match_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "draft_failed", "message": "Не смог набросать черновик."},
        ) from exc

    if not result.ok:
        if result.error == "forbidden":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "forbidden", "message": "Это не твоя карточка."},
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "Карточка устарела."},
        )
    return DraftOut(match_id=match_id, kind=result.kind, text=result.text)
