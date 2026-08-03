"""Нормализация полей вакансии для карточки.

Не фильтрует и не отбрасывает возможности — только причёсывает title/org/description.
Используется при ingestion и как страховка в format_card (старые записи в БД).

Спека: docs/services/ingestion.md, docs/services/bot.md
"""

from __future__ import annotations

import re

from app.ingestion.schemas import OpportunityDraft

_WS_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"<[^>]+>")

# Хвост питча компании после роли.
_PITCH_CUT_RE = re.compile(
    r"\s*[—–\-]\s*(?:это|мы|наш[аеи]?|компания|экосистема|сервис|платформа)\b.*$",
    re.I | re.S,
)
_SENTENCE_END_RE = re.compile(r"[.!?](?:\s+|$)")

# Типичные роли в начале (RU/EN).
_ROLE_START_RE = re.compile(
    r"^(?P<role>"
    r"(?:(?:Senior|Junior|Middle|Lead|Principal|Staff|Chief)\s+)?"
    r"(?:"
    r"Head\s+of\s+(?:Digital\s+)?Product|"
    r"Product\s+(?:Owner|Manager|Lead|Director|Analyst)|"
    r"CPO|CTO|CEO|"
    r"Директор\s+по\s+продукту|"
    r"Руководитель\s+(?:цифрового\s+)?продукта|"
    r"Руководитель\s+направления|"
    r"Владелец\s+продукта|"
    r"Менеджер\s+продукта|"
    r"Продакт(?:[\-\s]?менеджер)?|"
    r"Product\s+Manager|"
    r"Project\s+Manager|"
    r"Менеджер\s+проектов"
    r"))"
    r"(?P<rest>.*)$",
    re.I,
)

_IN_COMPANY_RE = re.compile(
    r"^(?P<title>.+?)\s+(?:в|at|@)\s+(?P<org>.+)$",
    re.I,
)

_TITLE_MAX = 100
_DISPLAY_TITLE_MAX = 90


def _clean(text: str) -> str:
    text = _TAG_RE.sub(" ", text or "")
    return _WS_RE.sub(" ", text).replace("\xa0", " ").strip(" ·—–-|")


def clean_job_title(raw: str | None, *, org: str | None = None) -> str:
    """Короткая роль без питча компании. Не возвращает пустое — fallback на укороченный raw."""
    text = _clean(raw or "")
    if not text:
        return "Вакансия"

    text = _PITCH_CUT_RE.sub("", text).strip(" ·—–-|")

    # Если после обрезки всё ещё абзац — взять до первой точки, если она похожа на роль.
    if len(text) > _TITLE_MAX:
        m = _SENTENCE_END_RE.search(text)
        if m and m.start() >= 12:
            head = text[: m.start()].strip()
            if len(head) <= _TITLE_MAX and not _PITCH_CUT_RE.search(head + " — это x"):
                text = head

    # «Роль в Компании»
    m_in = _IN_COMPANY_RE.match(text)
    if m_in and len(m_in.group("title")) <= _TITLE_MAX:
        text = m_in.group("title").strip()

    # «Менеджер продукта Физикл» → роль + остаток как org (если org пуст — снаружи)
    m_role = _ROLE_START_RE.match(text)
    if m_role:
        role = _clean(m_role.group("role"))
        rest = _clean(m_role.group("rest") or "")
        # остаток из 1–3 слов без «это/который» — вероятно бренд
        if rest and not re.search(r"\b(это|который|которая|которые|помогает)\b", rest, re.I):
            words = rest.split()
            if 1 <= len(words) <= 3 and len(rest) <= 40:
                text = role
            else:
                text = role if len(role) >= 8 else text
        else:
            text = role

    # Разделители « · » / « | »
    for sep in (" · ", " | ", " / ", " — ", " – "):
        if sep in text:
            left = text.split(sep, 1)[0].strip()
            if 8 <= len(left) <= _TITLE_MAX:
                text = left
                break

    if len(text) > _TITLE_MAX:
        cut = text[: _TITLE_MAX - 1].rsplit(" ", 1)[0]
        text = (cut or text[: _TITLE_MAX - 1]).rstrip(".,;:") + "…"

    # Не оставлять org в title, если org уже известен
    if org:
        org_c = _clean(org)
        if org_c and text.lower().endswith(org_c.lower()):
            text = text[: -len(org_c)].strip(" ·—–-|,")

    return text or _clean(raw or "")[:_TITLE_MAX] or "Вакансия"


def guess_org_from_title(raw: str | None, *, existing_org: str | None = None) -> str | None:
    """Достать компанию из сырого title, если org ещё нет."""
    if existing_org and _clean(existing_org):
        return _clean(existing_org)
    text = _clean(raw or "")
    if not text:
        return None

    text_cut = _PITCH_CUT_RE.sub("", text).strip(" ·—–-|")
    m_in = _IN_COMPANY_RE.match(text_cut)
    if m_in:
        org = _clean(m_in.group("org"))
        if 2 <= len(org) <= 60:
            return org

    m_role = _ROLE_START_RE.match(text_cut)
    if m_role:
        rest = _clean(m_role.group("rest") or "")
        if rest and not re.search(r"\b(это|который|которая|помогает)\b", rest, re.I):
            words = rest.split()
            if 1 <= len(words) <= 3 and len(rest) <= 40:
                return rest
    return None


def clean_job_description(
    description: str | None,
    *,
    title: str | None = None,
) -> str | None:
    """Убрать дубль title из начала description; пустое → None."""
    text = _clean(description or "")
    if not text:
        return None
    t = _clean(title or "")
    if t and text.lower().startswith(t.lower()):
        text = text[len(t) :].lstrip(" ·—–-|:;")
        text = _clean(text)
    if len(text) < 20:
        return None
    return text


def normalize_job_draft(draft: OpportunityDraft) -> OpportunityDraft:
    """In-place причёска job-draft. Talks не трогаем. Вакансию не отбрасываем."""
    if (draft.type or "job") != "job":
        return draft
    raw_title = draft.title
    org = guess_org_from_title(raw_title, existing_org=draft.org)
    title = clean_job_title(raw_title, org=org)
    desc = clean_job_description(draft.description, title=title)
    # Если description был = сырой питч и title почистили — оставить сырой текст в desc
    if desc is None and draft.description:
        raw_desc = _clean(draft.description)
        if raw_desc and raw_desc.lower() != title.lower():
            # убрать обрезанный title из начала сырого
            desc = clean_job_description(raw_desc, title=title) or raw_desc
            if desc and len(desc) < 40 and raw_title and len(_clean(raw_title)) > len(title) + 20:
                # суть = хвост после короткой роли из сырого title
                desc = clean_job_description(_clean(raw_title), title=title) or desc
    draft.title = title
    if org:
        draft.org = org
    if desc:
        draft.description = desc
    elif draft.description and _clean(draft.description).lower() == title.lower():
        draft.description = None
    return draft


def display_title(raw: str | None, *, org: str | None = None) -> str:
    """Страховка для format_card (в т.ч. старые записи)."""
    title = clean_job_title(raw, org=org)
    if len(title) > _DISPLAY_TITLE_MAX:
        cut = title[: _DISPLAY_TITLE_MAX - 1].rsplit(" ", 1)[0]
        title = (cut or title[: _DISPLAY_TITLE_MAX - 1]).rstrip(".,;:") + "…"
    return title
