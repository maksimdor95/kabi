"""Тесты seed-каталога площадок выступлений (M3). Конференции — в open_cfp (M5)."""

import asyncio

from app.ingestion.talks.seed_connector import TalkPlacesConnector, load_places, place_to_draft
from app.ingestion.talks.url_quality import is_actionable_cfp_url


def test_load_places_has_media_no_conferences():
    places = load_places()
    # После сужения каталога — только product-релевантные площадки (enabled≠false).
    assert len(places) >= 15
    kinds = {p["kind"] for p in places}
    assert "media" in kinds
    assert "podcast" in kinds or "community" in kinds
    # CFP-конференции переехали в data/open_cfp.yaml
    assert "conference" not in kinds
    ids = {p["id"] for p in places}
    assert "vc" in ids
    assert "cnews" in ids
    assert "skillfactory" in ids
    # Массовые СМИ выключены (enabled: false)
    assert "rbc" not in ids
    assert "kommersant" not in ids
    assert "productsense" not in ids
    assert "youtube-career" not in ids
    assert "digital-officer" not in ids


def test_actionable_cfp_url():
    assert is_actionable_cfp_url("https://productsense.io/submit") is True
    assert is_actionable_cfp_url("https://egconf.io/") is False
    assert is_actionable_cfp_url("https://www.youtube.com/") is False
    assert is_actionable_cfp_url(None) is False


def test_root_cfp_url_not_treated_as_application_page():
    place = {
        "id": "eg",
        "name": "Epic",
        "kind": "conference",
        "how": "cfp_talk",
        "url": "https://egconf.io/",
        "cfp_url": "https://egconf.io/",
        "topics": ["growth"],
    }
    draft = place_to_draft(place)
    assert draft.meta["cfp_url"] is None
    assert draft.url == "https://egconf.io/"


def test_place_to_draft_talk_with_deadline():
    place = {
        "id": "demo",
        "name": "Demo Conf",
        "kind": "conference",
        "how": "cfp_talk",
        "url": "https://example.com",
        "cfp_url": "https://example.com/cfp",
        "deadline": "2026-08-15",
        "status": "open",
        "topics": ["product", "skills"],
    }
    draft = place_to_draft(place)
    assert draft.type == "talk"
    assert draft.source == "talk_places_seed"
    assert draft.external_id == "demo"
    assert "product" in (draft.tags or [])
    assert draft.deadline is not None
    assert draft.deadline.year == 2026
    assert draft.deadline.month == 8
    assert draft.url == "https://example.com/cfp"
    assert draft.meta["cfp_url"] == "https://example.com/cfp"
    assert draft.meta["topics"] == ["product", "skills"]


def test_media_has_no_invented_deadline():
    place = {
        "id": "media1",
        "name": "Demo Media",
        "kind": "media",
        "how": "expert_comment",
        "url": "https://example.com",
        "topics": ["skills"],
    }
    draft = place_to_draft(place)
    assert draft.deadline is None
    assert draft.url == "https://example.com"


def test_connector_fetch_offline():
    drafts = asyncio.run(TalkPlacesConnector(live_cfp=False).fetch())
    assert len(drafts) >= 15
    assert all(d.type == "talk" for d in drafts)
    assert len({d.external_id for d in drafts}) == len(drafts)
    by_id = {d.external_id: d for d in drafts}
    assert "vc" in by_id
    assert "rbc" not in by_id
    assert all(d.meta.get("kind") != "conference" for d in drafts if d.meta)
