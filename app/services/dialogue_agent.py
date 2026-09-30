"""Ядро «менеджера»: онбординг и диалог.

Спека: docs/services/dialogue-agent.md  (M1 онбординг + M9 советник)
Онбординг ведётся по шагам через profile.onboarding_step.
Свободный чат: windowed history + advisor tools.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Profile, User
from app.enrichment.base import (
    enrich_from_links,
    format_signals_summary,
    signals_to_profile_patch,
)
from app.services import advisor_tools
from app.services import dialog_memory
from app.services import profile as profile_service
from app.services.advisor_profile import (
    extract_chat_profile_update,
    format_update_note,
)
from app.services.onboarding import (
    STEPS,
    extract_urls,
    filter_useful_links,
    is_restart_request,
    parse_answer,
)

_MANAGER_PERSONA = (
    "Ты — персональный карьерный менеджер пользователя (как менеджер у звезды). "
    "Общаешься тепло, по делу, коротко. "
    "Не начинай ответы с приветствия («Здравствуйте», «Привет» и т.п.) — сразу по сути; "
    "пользователь уже в чате. "
    "Не выдумывай факты о пользователе — только профиль и данные из блока инструментов. "
    "Не выдумывай вакансии, компании, конференции и дедлайны: если в инструментах пусто — "
    "скажи честно и предложи /today, /talks или /pitch. "
    "Не пиарь масс-медиа и ТВ evergreen (НТВ, утренние шоу и т.п.) — зона: продукт, "
    "релевантные конференции и питч только если пользователь просит. "
    "Не составляй утренние планёры и to-do на день, если тебя об этом прямо не просят — "
    "твоя зона: карьера, вакансии, выступления. "
    "Обращайся нейтрально по роду (без «ты занята» / «ты готова»). "
    "Не используй жаргон CFP в ответах пользователю — говори «конференции» / «срок подачи заявки»."
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
    "Готово — профиль собран. Сейчас принесу свежие вакансии. 🎯\n\n"
    "Команды: /today · /profile · /schedule · /saved\n"
    "Ссылки можно докинуть в любой момент.\n"
    "Онбординг заново — «начать заново»."
)


@dataclass
class AgentReply:
    text: str
    finished: bool = False
    buttons: tuple[str, ...] = ()
    remove_keyboard: bool = False
    trigger_digest: bool = False  # Sprint A: после онбординга сразу /today
    entry: str | None = None  # cv|text|link для analytics


def _reply_for_step(
    step_idx: int, preface: str | None = None, *, profile: Profile | None = None
) -> AgentReply:
    step = STEPS[step_idx]
    question = step.question
    if step.key == "confirm_roles" and profile is not None:
        roles = ", ".join(profile.roles or []) or "пока пусто"
        question = (
            f"Так вижу целевые роли: {roles}.\n"
            "Ок — или напиши 1–2 роли своими словами."
        )
    text = f"{preface}\n\n{question}" if preface else question
    return AgentReply(text=text, buttons=step.buttons)


_SENIORITY_RE = re.compile(
    r"\b(middle|senior|lead|head|cpo|c-level|директор|мидл|сеньор)\b",
    re.I,
)


def roles_need_level(roles: list[str] | None) -> bool:
    """True если в ролях нет явного грейда — спросим шаг level."""
    blob = " ".join(roles or [])
    if not blob.strip():
        return True
    return _SENIORITY_RE.search(blob) is None


def apply_level_to_roles(roles: list[str] | None, level: str) -> list[str]:
    """Префикс уровня к ролям, если его ещё нет."""
    label = (level or "").strip()
    base = [r for r in (roles or []) if r and str(r).strip()]
    if not label:
        return base
    if not base:
        return [label]
    out: list[str] = []
    for r in base:
        if _SENIORITY_RE.search(r) or label.lower() in r.lower():
            out.append(r)
        else:
            out.append(f"{label} {r}")
    return out


def _has_salary(profile: Profile) -> bool:
    sal = profile.salary_expectation or {}
    return isinstance(sal, dict) and bool(sal.get("min"))


def _should_skip_step(profile: Profile, step_key: str) -> bool:
    if step_key == "salary":
        return _has_salary(profile)
    if step_key == "level":
        return not roles_need_level(profile.roles)
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
        elif STEPS[idx].key == "level":
            notes.append("Уровень ролей уже виден из резюме — шаг пропускаю.")
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
    from app.services import analytics

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
        await analytics.emit(
            session,
            name="onboarding_step_completed",
            profile_id=profile.id,
            props={"final": True},
        )
        return AgentReply(
            text=_DONE_TEXT, finished=True, remove_keyboard=True, trigger_digest=True
        )
    preface = "\n\n".join(notes) if notes else None
    await analytics.emit(
        session,
        name="onboarding_step_entered",
        profile_id=profile.id,
        props={"step": step_idx, "key": STEPS[step_idx].key},
    )
    return _reply_for_step(step_idx, preface=preface, profile=profile)


async def continue_onboarding(session: AsyncSession, profile: Profile) -> AgentReply:
    """Продолжить с текущего шага (без сброса)."""
    from app.services import analytics

    if is_onboarding_complete(profile):
        return AgentReply(
            text=_DONE_TEXT, finished=True, remove_keyboard=True, trigger_digest=True
        )
    notes: list[str] = []
    idx = _skip_ahead(profile, profile.onboarding_step, notes)
    profile.onboarding_step = idx
    if idx >= len(STEPS):
        return AgentReply(
            text=_DONE_TEXT, finished=True, remove_keyboard=True, trigger_digest=True
        )
    preface = "\n\n".join(notes) if notes else None
    await analytics.emit(
        session,
        name="onboarding_step_entered",
        profile_id=profile.id,
        props={"step": idx, "key": STEPS[idx].key},
    )
    return _reply_for_step(idx, preface=preface, profile=profile)


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
    from app.services import analytics

    await analytics.emit(
        session,
        name="links_added",
        profile_id=profile.id,
        props={"n": len(useful), "source": "mid"},
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
    from app.services import analytics

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

    patch = dict(parsed.patch)
    level = patch.pop("_level", None)
    if level:
        patch["roles"] = apply_level_to_roles(profile.roles, str(level))

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
            await analytics.emit(
                session,
                name="links_added",
                profile_id=profile.id,
                props={"n": len(links), "source": "onboarding"},
            )
            summary = await _run_enrichment(session, profile)
            if summary:
                preface_parts.append(summary)
        elif profile.enrichment_consent:
            preface_parts.append(_NO_LINKS_NOTE)

    await analytics.emit(
        session,
        name="onboarding_step_completed",
        profile_id=profile.id,
        props={"step": step_idx, "key": step.key},
    )

    next_idx = step_idx + 1
    next_idx = _skip_ahead(profile, next_idx, preface_parts)
    profile.onboarding_step = next_idx
    await session.flush()

    if next_idx < len(STEPS):
        await analytics.emit(
            session,
            name="onboarding_step_entered",
            profile_id=profile.id,
            props={"step": next_idx, "key": STEPS[next_idx].key},
        )
        preface = "\n\n".join(preface_parts) if preface_parts else None
        return _reply_for_step(next_idx, preface=preface, profile=profile)

    profile_service.refresh_readiness(profile)
    await session.flush()
    await analytics.emit(
        session,
        name="onboarding_step_completed",
        profile_id=profile.id,
        props={"final": True},
    )
    if profile.ready_for_matching:
        return AgentReply(text=_DONE_TEXT, finished=True, trigger_digest=True)
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
    from app.services import analytics

    profile = await profile_service.get_profile(session, user.id)
    if profile is None:
        from app.domain.profile import ProfileDraft
        from app.services import bootstrap as bootstrap_service

        useful, _junk = filter_useful_links(extract_urls(text))
        if useful:
            draft = ProfileDraft(
                roles=["Product Manager"],
                skills=[],
                location="не указано",
                work_mode="remote",
            )
            profile = await profile_service.apply_cv_draft(session, user.id, draft)
            await profile_service.update_profile(
                session,
                profile,
                {"enrichment_consent": True, "source_links": {"links": useful}},
            )
            await analytics.emit(
                session,
                name="entry_chosen",
                profile_id=profile.id,
                props={"entry": "link"},
            )
            summary = await _run_enrichment(session, profile)
            reply = await start_onboarding(session, profile)
            preface = summary or "Ссылки сохранил — уточним профиль."
            return AgentReply(
                text=f"{preface}\n\n{reply.text}",
                buttons=reply.buttons,
                finished=reply.finished,
                remove_keyboard=reply.remove_keyboard,
                trigger_digest=reply.trigger_digest,
            )

        if bootstrap_service.text_looks_like_profile_seed(text):
            try:
                draft = await bootstrap_service.draft_from_text(text)
            except Exception as exc:  # noqa: BLE001
                from app.observability.logging import get_logger

                get_logger("kabi.dialogue").warning("bootstrap_text_failed: %s", exc)
                return AgentReply(
                    text=(
                        "Не разобрал текст. Пришли PDF/DOCX резюме или напиши яснее:\n"
                        "роли, опыт, куда целишься."
                    )
                )
            profile = await profile_service.apply_cv_draft(session, user.id, draft)
            await analytics.emit(
                session,
                name="entry_chosen",
                profile_id=profile.id,
                props={"entry": "text", "roles_n": len(profile.roles or [])},
            )
            reply = await start_onboarding(session, profile)
            return AgentReply(
                text=f"Собрал черновик из текста.\n\n{reply.text}",
                buttons=reply.buttons,
                finished=reply.finished,
                remove_keyboard=reply.remove_keyboard,
                trigger_digest=reply.trigger_digest,
            )

        low = text.strip().lower()
        if low in {"2", "текст", "text", "2)", "вариант 2"}:
            return AgentReply(
                text=(
                    "Ок, напиши пару предложений своими словами:\n"
                    "роли, опыт, куда целишься.\n"
                    "Например: «Product owner в банке, 5 лет, ищу Head of Product»."
                )
            )
        if low in {"1", "pdf", "docx", "резюме", "1)"}:
            return AgentReply(text="Пришли файл резюме PDF или DOCX.")
        if low in {"3", "ссылка", "3)", "linkedin", "hh"}:
            return AgentReply(
                text="Пришли ссылку на HH или LinkedIn (/in/…)."
            )

        return AgentReply(
            text=(
                "Начнём с профиля. Можно так:\n"
                "1) резюме PDF/DOCX\n"
                "2) текст: роли и опыт парой предложений\n"
                "3) ссылка на HH / LinkedIn /in/…"
            )
        )

    if is_restart_request(text):
        await dialog_memory.clear(user.id)
        return await start_onboarding(session, profile)

    if profile.onboarding_step < len(STEPS):
        return await _advance_onboarding(session, profile, text)

    useful, junk = filter_useful_links(extract_urls(text))
    if useful and profile.enrichment_consent:
        merged = _merge_links(profile, useful)
        await profile_service.update_profile(
            session, profile, {"source_links": {"links": merged}}
        )
        from app.services import analytics

        await analytics.emit(
            session,
            name="links_added",
            profile_id=profile.id,
            props={"n": len(useful), "source": "post"},
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

    return await _free_chat(session, profile, text)


def _build_advisor_messages(
    *,
    profile: Profile,
    history: list[dict[str, str]],
    tool_context: str,
    user_text: str,
    profile_update_note: str = "",
) -> list[dict[str, str]]:
    """Собрать messages для LLM: persona + профиль + tools + история + реплика."""
    context = profile_service.profile_to_text(profile)
    system_parts = [_MANAGER_PERSONA, f"Краткий профиль:\n{context or '(пусто)'}"]
    if profile_update_note:
        system_parts.append(
            f"Только что сохранено в профиль: {profile_update_note} "
            "Коротко подтверди это пользователю."
        )
    if tool_context:
        system_parts.append(
            "Данные из инструментов (единственный источник фактов по вакансиям/"
            f"конференциям/расписанию):\n{tool_context}"
        )
    messages: list[dict[str, str]] = [{"role": "system", "content": "\n\n".join(system_parts)}]
    for msg in history:
        role = msg.get("role")
        content = (msg.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_text})
    return messages


async def _free_chat(
    session: AsyncSession, profile: Profile, text: str
) -> AgentReply:
    from app.llm import client as llm

    update = extract_chat_profile_update(text)
    update_note = ""
    if update.patch:
        await profile_service.update_profile(session, profile, update.patch)
        update_note = format_update_note(update)

    history = await dialog_memory.get_history(profile.user_id)
    tools = advisor_tools.select_tools(text)
    # После записи зарплаты/флагов полезно подтянуть карточку профиля в контекст.
    if update.patch and "get_profile" not in tools:
        tools = ["get_profile", *tools]
    tool_context = await advisor_tools.run_tools(session, profile, tools)
    messages = _build_advisor_messages(
        profile=profile,
        history=history,
        tool_context=tool_context,
        user_text=text,
        profile_update_note=update_note,
    )
    answer = await llm.complete_messages(messages, tier="primary")
    await dialog_memory.append_turn(profile.user_id, text, answer)
    return AgentReply(text=answer, finished=True)  # finished → оставить главное меню
