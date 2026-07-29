"""Ядро «менеджера»: онбординг и диалог.

Спека: docs/services/dialogue-agent.md  (этап M1)
Онбординг ведётся по шагам через profile.onboarding_step.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Profile, User
from app.enrichment.base import (
    enrich_from_links,
    format_signals_summary,
    signals_to_profile_patch,
)
from app.services import profile as profile_service
from app.services.onboarding import (
    STEPS,
    extract_urls,
    filter_useful_links,
    is_restart_request,
    parse_answer,
)

_MANAGER_PERSONA = (
    "Ты — персональный карьерный менеджер пользователя (как менеджер у звезды). "
    "Ты знаешь его профиль и общаешься тепло, по делу, проактивно. "
    "Не выдумывай факты о пользователе. Не составляй утренние планёры и to-do на день, "
    "если тебя об этом прямо не просят — твоя зона: карьера, вакансии, выступления. "
    "Обращайся нейтрально по роду (без «ты занята» / «ты готова»)."
)

_NO_LINKS_NOTE = (
    "Ок, согласие принял. Чтобы «сходить самому», мне нужна хотя бы одна твоя "
    "ссылка (HH / LinkedIn / запись выступления) — чужие профили по имени не "
    "собираю. Можно кинуть позже. А пока продолжим."
)

_JUNK_LINKS_NOTE = (
    "Это не ссылка на профиль (лента LinkedIn / логин не подойдут). "
    "Нужна персональная: linkedin.com/in/… или hh.ru/resume/…"
)

_ASK_PROFILE_LINK = (
    "Кинь ссылку на свой профиль: linkedin.com/in/… или публичное резюме HH. "
    "Лента (linkedin.com/feed) не читается."
)

_DONE_TEXT = (
    "Готово — профиль собран. Дальше ищу сам. 🎯\n\n"
    "Меню внизу или команды:\n"
    "/profile — что я о тебе знаю\n"
    "/today — вакансии\n"
    "/pitch — СМИ и подкасты для питча\n"
    "/talks — конференции с датой подачи заявки\n"
    "/schedule — когда присылать вакансии и выступления\n"
    "/saved — избранное\n\n"
    "Можно докинуть ссылки (сайт, LinkedIn) в любой момент.\n"
    "Онбординг заново — напиши «начать заново»."
)


@dataclass
class AgentReply:
    text: str
    finished: bool = False
    buttons: tuple[str, ...] = ()
    remove_keyboard: bool = False


def _reply_for_step(step_idx: int, preface: str | None = None) -> AgentReply:
    step = STEPS[step_idx]
    text = f"{preface}\n\n{step.question}" if preface else step.question
    return AgentReply(text=text, buttons=step.buttons)


def _has_salary(profile: Profile) -> bool:
    sal = profile.salary_expectation or {}
    return isinstance(sal, dict) and bool(sal.get("min"))


def _should_skip_step(profile: Profile, step_key: str) -> bool:
    if step_key == "salary":
        return _has_salary(profile)
    return False


def _skip_ahead(profile: Profile, start_idx: int, notes: list[str]) -> int:
    """Продвинуть индекс через шаги, которые уже закрыты (напр. ЗП из CV)."""
    idx = start_idx
    while idx < len(STEPS) and _should_skip_step(profile, STEPS[idx].key):
        if STEPS[idx].key == "salary":
            sal = profile.salary_expectation or {}
            amount = int(sal.get("min") or 0)
            currency = sal.get("currency") or "RUB"
            notes.append(f"Зарплатный минимум взял из резюме: от {amount} {currency}.")
        idx += 1
    return idx


def _merge_links(profile: Profile, new_links: list[str]) -> list[str]:
    existing = list((profile.source_links or {}).get("links") or [])
    useful_existing, _ = filter_useful_links(existing)
    merged = useful_existing[:]
    for link in new_links:
        if link not in merged:
            merged.append(link)
    return merged


def is_onboarding_complete(profile: Profile) -> bool:
    return profile.onboarding_step >= len(STEPS)


async def start_onboarding(session: AsyncSession, profile: Profile) -> AgentReply:
    """Начать онбординг с нуля (явный сброс).

    Сбрасываем source_links и согласие: иначе при «профиле другого человека»
    обогащение подтянет чужой LinkedIn с прошлого прогона.
    """
    notes: list[str] = []
    await profile_service.update_profile(
        session,
        profile,
        {"source_links": {"links": []}, "enrichment_consent": False},
    )
    step_idx = _skip_ahead(profile, 0, notes)
    profile.onboarding_step = step_idx
    await session.flush()
    if step_idx >= len(STEPS):
        profile_service.refresh_readiness(profile)
        return AgentReply(text=_DONE_TEXT, finished=True, remove_keyboard=True)
    preface = "\n\n".join(notes) if notes else None
    return _reply_for_step(step_idx, preface=preface)


async def continue_onboarding(profile: Profile) -> AgentReply:
    """Продолжить с текущего шага (без сброса)."""
    if is_onboarding_complete(profile):
        return AgentReply(text=_DONE_TEXT, finished=True, remove_keyboard=True)
    notes: list[str] = []
    idx = _skip_ahead(profile, profile.onboarding_step, notes)
    profile.onboarding_step = idx
    if idx >= len(STEPS):
        return AgentReply(text=_DONE_TEXT, finished=True, remove_keyboard=True)
    preface = "\n\n".join(notes) if notes else None
    return _reply_for_step(idx, preface=preface)


async def _run_enrichment(session: AsyncSession, profile: Profile) -> str | None:
    """Обогатить профиль по сохранённым ссылкам. Вернуть текст-сводку или None."""
    links_blob = profile.source_links or {}
    links, _ = filter_useful_links(list(links_blob.get("links") or []))
    if not links:
        return None
    await profile_service.update_profile(session, profile, {"source_links": {"links": links}})
    signals = await enrich_from_links(profile.user_id, links)
    patch = signals_to_profile_patch(
        signals,
        existing_skills=list(profile.skills or []),
        existing_topics=list(profile.speaking_topics or []),
    )
    patch.pop("source_links", None)
    if patch:
        await profile_service.update_profile(session, profile, patch)
    return format_signals_summary(signals)


async def _handle_links_mid_onboarding(
    session: AsyncSession, profile: Profile, text: str
) -> AgentReply | None:
    """Если на шаге вопросов прислали ссылки — обогащаем и повторяем текущий вопрос."""
    step = STEPS[profile.onboarding_step]
    if step.key == "consent_links":
        return None

    urls = extract_urls(text)
    if not urls:
        return None

    useful, junk = filter_useful_links(urls)
    remainder = text
    for u in urls:
        remainder = remainder.replace(u, "")
        remainder = remainder.replace(u.removeprefix("https://"), "")
        remainder = remainder.replace(u.removeprefix("http://"), "")
    if remainder.strip() and len(remainder.strip()) > 8:
        return None

    if not useful:
        return AgentReply(
            text="\n\n".join([_JUNK_LINKS_NOTE, step.question]),
            buttons=step.buttons,
        )

    merged = _merge_links(profile, useful)
    await profile_service.update_profile(
        session,
        profile,
        {"enrichment_consent": True, "source_links": {"links": merged}},
    )
    summary = await _run_enrichment(session, profile)
    parts = [summary or "Ссылки сохранил."]
    if junk:
        parts.append(_JUNK_LINKS_NOTE)
    parts.append(step.question)
    return AgentReply(text="\n\n".join(parts), buttons=step.buttons)


def _is_plain_no(text: str) -> bool:
    from app.services.onboarding import _is_negative

    return _is_negative(text) and not extract_urls(text)


async def _advance_onboarding(
    session: AsyncSession, profile: Profile, text: str
) -> AgentReply:
    step_idx = profile.onboarding_step
    step = STEPS[step_idx]

    mid = await _handle_links_mid_onboarding(session, profile, text)
    if mid is not None:
        return mid

    if step.key == "consent_links":
        urls = extract_urls(text)
        useful, _junk = filter_useful_links(urls)
        if urls and not useful and not _is_plain_no(text):
            return AgentReply(text=_ASK_PROFILE_LINK, buttons=step.buttons)

    parsed = parse_answer(step.key, text)
    if not parsed.ok:
        return AgentReply(text=step.hint, buttons=step.buttons)

    patch = parsed.patch
    if patch:
        # На шаге согласия — замена ссылок (не мержим со старым LinkedIn).
        # На остальных шагах source_links в патче не ожидаем.
        if step.key != "consent_links" and "source_links" in patch:
            new_links = list((patch["source_links"] or {}).get("links") or [])
            patch["source_links"] = {"links": _merge_links(profile, new_links)}
        await profile_service.update_profile(session, profile, patch)

    preface_parts: list[str] = []

    if step.key == "consent_links":
        links, _ = filter_useful_links(list((profile.source_links or {}).get("links") or []))
        if links:
            await profile_service.update_profile(
                session, profile, {"source_links": {"links": links}}
            )
            summary = await _run_enrichment(session, profile)
            if summary:
                preface_parts.append(summary)
        elif profile.enrichment_consent:
            preface_parts.append(_NO_LINKS_NOTE)

    next_idx = step_idx + 1
    next_idx = _skip_ahead(profile, next_idx, preface_parts)
    profile.onboarding_step = next_idx
    await session.flush()

    if next_idx < len(STEPS):
        preface = "\n\n".join(preface_parts) if preface_parts else None
        return _reply_for_step(next_idx, preface=preface)

    profile_service.refresh_readiness(profile)
    await session.flush()
    if profile.ready_for_matching:
        return AgentReply(text=_DONE_TEXT, finished=True)
    missing = _missing_required(profile)
    return AgentReply(
        text=(
            "Почти всё. Не хватает обязательного: "
            + ", ".join(missing)
            + ". Заполним? Можно прислать резюме или написать «начать заново»."
        ),
        finished=False,
        remove_keyboard=True,
    )


def _missing_required(profile: Profile) -> list[str]:
    labels = {
        "roles": "целевые роли",
        "location": "город",
        "work_mode": "формат работы",
        "salary_expectation": "зарплатные ожидания",
        "skills": "навыки",
        "enrichment_consent": "согласие на обогащение",
    }
    missing = []
    for field_name, label in labels.items():
        if not getattr(profile, field_name):
            missing.append(label)
    return missing


async def handle_message(session: AsyncSession, user: User, text: str) -> AgentReply:
    """Точка входа: онбординг, если не завершён, иначе — свободный диалог."""
    profile = await profile_service.get_profile(session, user.id)
    if profile is None:
        return AgentReply(
            text="Пришли, пожалуйста, своё резюме (PDF или DOCX) — начнём с него."
        )

    if is_restart_request(text):
        return await start_onboarding(session, profile)

    if profile.onboarding_step < len(STEPS):
        return await _advance_onboarding(session, profile, text)

    useful, junk = filter_useful_links(extract_urls(text))
    if useful and profile.enrichment_consent:
        merged = _merge_links(profile, useful)
        await profile_service.update_profile(
            session, profile, {"source_links": {"links": merged}}
        )
        summary = await _run_enrichment(session, profile)
        parts = []
        if summary:
            parts.append(summary)
        if junk:
            parts.append(_JUNK_LINKS_NOTE)
        parts.append(
            "Могу ещё что-то уточнить или ищу возможности (/today, /pitch, /talks, /saved)."
        )
        return AgentReply(text="\n\n".join(parts))
    if junk and not useful:
        return AgentReply(text=_ASK_PROFILE_LINK)

    return await _free_chat(profile, text)


async def _free_chat(profile: Profile, text: str) -> AgentReply:
    from app.llm import client as llm

    context = profile_service.profile_to_text(profile)
    answer = await llm.complete(
        f"Профиль пользователя:\n{context}\n\nСообщение пользователя: {text}",
        system=_MANAGER_PERSONA,
        tier="primary",
    )
    return AgentReply(text=answer, finished=True)  # finished → оставить главное меню
