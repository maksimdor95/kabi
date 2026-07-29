"""Тесты M6 discovery filters + PaperCall parsers (без сети)."""

from datetime import datetime, timezone

from app.ingestion.talks.discover_connector import event_to_draft
from app.ingestion.talks.discovery_filters import matches_niche, matches_region
from app.ingestion.talks.papercall_discover import (
    PapercallEvent,
    PapercallListing,
    filter_listings,
    parse_event_html,
    parse_listing_html,
)


_LISTING_HTML = """
<a href="https://www.papercall.io/conf42-ai-agents-2026">Conf42 AI Agents 2026 - Online</a>
<a href="https://www.papercall.io/conf42-ai-agents-2026">Submit Now!</a>
<a href="https://www.papercall.io/devops-midwest">DevOps Midwest 2026 - St. Louis, MO</a>
<a href="https://www.papercall.io/product-summit-msk">Product Summit - Moscow</a>
<a href="https://www.papercall.io/pricing">Pricing</a>
"""

_EVENT_HTML = """
<html><body>
Conf42 AI Agents 2026 Online September 24, 2026
https://www.conf42.com/agents2026
Tags: Autonomy , Orchestration , Reasoning , Planning
CFP closes at August 24, 2026 20:11 UTC
CFP Description something useful
</body></html>
"""


def test_matches_region_online_and_moscow():
    assert matches_region("Online") is True
    assert matches_region("Moscow") is True
    assert matches_region("St. Louis, MO", title="DevOps Midwest") is False
    assert matches_region("Denver, CO / Online") is True


def test_matches_niche_product():
    assert matches_niche("Conf42 AI Agents 2026") is True
    assert matches_niche("random knitting meetup") is False
    assert matches_niche("Product Summit Moscow") is True


def test_parse_listing_and_filter():
    listings = parse_listing_html(_LISTING_HTML)
    slugs = {x.slug for x in listings}
    assert "conf42-ai-agents-2026" in slugs
    assert "product-summit-msk" in slugs
    assert "pricing" not in slugs
    filtered = filter_listings(listings)
    fslugs = {x.slug for x in filtered}
    assert "conf42-ai-agents-2026" in fslugs
    assert "product-summit-msk" in fslugs
    assert "devops-midwest" not in fslugs  # US offline


def test_parse_event_deadline():
    listing = PapercallListing(
        slug="conf42-ai-agents-2026",
        name="Conf42 AI Agents 2026",
        location="Online",
        cfp_url="https://www.papercall.io/conf42-ai-agents-2026",
    )
    ev = parse_event_html(_EVENT_HTML, listing)
    assert ev.deadline is not None
    assert ev.deadline.year == 2026
    assert ev.deadline.month == 8
    assert ev.deadline.day == 24
    assert "Autonomy" in ev.topics or "Planning" in ev.topics
    assert ev.open is True  # deadline in future relative to "today" Jul 2026


def test_event_to_draft():
    ev = PapercallEvent(
        slug="x",
        name="Demo",
        location="Online",
        cfp_url="https://www.papercall.io/x",
        deadline=datetime(2026, 9, 1, 23, 59, tzinfo=timezone.utc),
        event_start=None,
        topics=["product"],
        open=True,
    )
    d = event_to_draft(ev)
    assert d.source == "cfp_discovery"
    assert d.external_id == "papercall-x"
    assert d.meta["status"] == "open"
    assert d.meta["discovered_via"] == "papercall"
    assert d.url == "https://www.papercall.io/x"
