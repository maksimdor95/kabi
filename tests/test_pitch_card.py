"""Pitch 2.0: карточка «Как зайти», лимиты reason, actionable."""

from __future__ import annotations

from types import SimpleNamespace

from app.ingestion.talks.seed_connector import place_to_draft
from app.services import cards
from app.services.digest import DigestItem, _fmt_item
from app.services.matching import is_actionable_pitch_opp, is_evergreen_pitch


def _vc_item() -> DigestItem:
    draft = place_to_draft(
        {
            "id": "vc",
            "name": "vc.ru",
            "kind": "media",
            "how": "column",
            "url": "https://vc.ru/",
            "pitch_url": "https://vc.ru/write",
            "how_to": "Зарегистрируйся и опубликуй колонку через редактор vc.ru/write.",
            "example_topics": ["product discovery"],
            "topics": ["product"],
        }
    )
    opp = SimpleNamespace(
        type="talk",
        title=draft.title,
        org=draft.org,
        description=draft.description,
        location=draft.location,
        remote=draft.remote,
        salary=None,
        url=draft.url,
        source=draft.source,
        deadline=None,
        meta=draft.meta,
    )
    match = SimpleNamespace(id="00000000-0000-0000-0000-000000000001", score=0.9, reason="x" * 300)
    return _fmt_item(match, opp)  # type: ignore[arg-type]


def test_card_approach_from_how_to():
    item = _vc_item()
    approach = cards.card_approach(item)
    assert approach is not None
    assert "vc.ru/write" in approach or "колонку" in approach.lower()
    assert cards.card_summary(item) is None  # talk — без «Сути»


def test_pitch_reason_limit_higher_than_job():
    long = "А" * 400
    talk = DigestItem(
        match_id="1",
        score=1.0,
        reason=long,
        title="t",
        org="o",
        location=None,
        remote=True,
        salary=None,
        url=None,
        source=None,
        opp_type="talk",
    )
    job = DigestItem(
        match_id="2",
        score=1.0,
        reason=long,
        title="t",
        org="o",
        location=None,
        remote=False,
        salary=None,
        url=None,
        source=None,
        opp_type="job",
    )
    tr = cards.card_reason(talk)
    jr = cards.card_reason(job)
    assert tr and jr
    assert len(tr) > len(jr)
    assert len(tr) <= cards.REASON_LIMIT_PITCH + 5


def test_actionable_pitch_opp_reads_meta():
    opp = SimpleNamespace(
        type="talk",
        deadline=None,
        meta={"kind": "media", "how": "column", "actionable": True},
    )
    assert is_evergreen_pitch(opp) is True
    assert is_actionable_pitch_opp(opp) is True
    opp.meta["actionable"] = False
    assert is_actionable_pitch_opp(opp) is False


def test_fmt_item_hides_homepage_cta():
    draft = place_to_draft(
        {
            "id": "bare",
            "name": "Bare",
            "kind": "media",
            "how": "column",
            "url": "https://example.com/",
            "how_to": "Напиши редакции короткий комментарий на свежий инфоповод с должностью.",
            "topics": ["product"],
        }
    )
    opp = SimpleNamespace(
        type="talk",
        title=draft.title,
        org=draft.org,
        description=draft.description,
        location=None,
        remote=True,
        salary=None,
        url=draft.url,
        source=draft.source,
        deadline=None,
        meta=draft.meta,
    )
    match = SimpleNamespace(id="1", score=0.5, reason="fit")
    item = _fmt_item(match, opp)  # type: ignore[arg-type]
    assert item.hide_url is True
    assert item.url is None
    assert item.link_label is None
    assert item.approach
