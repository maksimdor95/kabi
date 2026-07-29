"""Тесты M5 open CFP коннектора (без сети — мок snapshot)."""

from datetime import datetime, timezone
from types import SimpleNamespace

from app.ingestion.talks.open_cfp_connector import (
    load_open_cfp_sources,
    source_to_draft,
    _status_from_snap,
)
from app.ingestion.talks.url_quality import is_actionable_cfp_url


def test_load_open_cfp_sources():
    rows = load_open_cfp_sources()
    assert len(rows) >= 3
    ids = {r["id"] for r in rows}
    assert "productsense-2026" in ids
    assert "infostart-apm-2026" in ids


def test_status_open_closed_unknown():
    future = datetime(2026, 12, 1, tzinfo=timezone.utc)
    past = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert _status_from_snap(True, None) == "open"
    assert _status_from_snap(False, future) == "closed"
    assert _status_from_snap(None, future) == "open"
    assert _status_from_snap(None, past) == "closed"
    assert _status_from_snap(None, None) == "unknown"


def test_source_to_draft_open():
    row = {
        "id": "demo-cfp",
        "name": "Demo Conf",
        "cfp_url": "https://example.com/cfp",
        "url": "https://example.com/",
        "topics": ["product", "продукт"],
        "location": "Москва",
    }
    snap = SimpleNamespace(
        open=True,
        deadline=datetime(2026, 8, 15, 23, 59, tzinfo=timezone.utc),
        event_start=datetime(2026, 10, 1, tzinfo=timezone.utc),
        event_end=None,
        note="приём открыт",
        raw_ok=True,
    )
    draft = source_to_draft(row, snap=snap)
    assert draft is not None
    assert draft.source == "open_cfp"
    assert draft.meta["status"] == "open"
    assert draft.meta["cfp_url"] == "https://example.com/cfp"
    assert draft.url == "https://example.com/cfp"
    assert "product" in (draft.tags or [])


def test_watch_only_and_root_url_skipped():
    row = {
        "id": "eg",
        "name": "Epic",
        "cfp_url": "https://egconf.io/",
        "url": "https://egconf.io/",
        "topics": ["growth"],
        "watch_only": True,
    }
    snap = SimpleNamespace(
        open=True, deadline=None, event_start=None, event_end=None, note="", raw_ok=True
    )
    assert source_to_draft(row, snap=snap) is None
    assert is_actionable_cfp_url("https://egconf.io/") is False
