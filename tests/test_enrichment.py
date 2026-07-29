"""Тесты enrichment: маршрутизация ссылок и merge сигналов."""

from app.enrichment.base import (
    ProfileSignals,
    format_signals_summary,
    merge_signals,
    pick_source,
    signals_to_profile_patch,
)


def test_pick_source_hh():
    src = pick_source("https://hh.ru/resume/abc123")
    assert src is not None
    assert src.name == "hh"


def test_pick_source_linkedin():
    src = pick_source("https://www.linkedin.com/in/marina")
    assert src is not None
    assert src.name == "linkedin"


def test_pick_source_talks():
    src = pick_source("https://www.youtube.com/watch?v=abc")
    assert src is not None
    assert src.name == "talks"


def test_pick_source_generic_fallback():
    src = pick_source("https://example.com/about")
    assert src is not None
    assert src.name == "generic"


def test_merge_signals_dedup():
    a = ProfileSignals(speaking_topics=["P&L", "AI"], extra_skills=["SQL"])
    b = ProfileSignals(speaking_topics=["AI", "Skills"], extra_skills=["SQL", "Figma"])
    m = merge_signals(a, b)
    assert m.speaking_topics == ["P&L", "AI", "Skills"]
    assert m.extra_skills == ["SQL", "Figma"]


def test_signals_to_profile_patch_merges():
    signals = ProfileSignals(
        speaking_topics=["монетизация"],
        extra_skills=["Figma"],
        job_search_status="active",
    )
    patch = signals_to_profile_patch(
        signals,
        existing_skills=["SQL"],
        existing_topics=["P&L"],
    )
    assert patch["skills"] == ["SQL", "Figma"]
    assert patch["speaking_topics"] == ["P&L", "монетизация"]
    assert patch["job_search_status"] == "active"


def test_format_signals_summary_empty():
    text = format_signals_summary(ProfileSignals())
    assert "ничего полезного" in text


def test_format_signals_summary_short_points_to_profile():
    text = format_signals_summary(
        ProfileSignals(speaking_topics=["рост"], extra_skills=["SQL"])
    )
    assert "профиле" in text
    assert "Темы выступлений" not in text
    # Без повторного CTA — следующий шаг онбординга и так рядом.
    assert "/profile" not in text


def test_linkedin_auth_wall_returns_note_not_fake_skills(monkeypatch):
    import asyncio

    from app.enrichment.sources import linkedin as li_mod

    async def fake_fallbacks(url: str):
        return "", "none"

    monkeypatch.setattr(li_mod, "_fetch_with_fallbacks", fake_fallbacks)
    signals = asyncio.run(li_mod.LinkedInSource().fetch("https://linkedin.com/in/x"))
    assert signals.source_links
    assert signals.extra_skills == []
    assert signals.speaking_topics == []
    assert any("login-wall" in n.lower() or "li_at" in n.lower() for n in signals.notes)


def test_linkedin_parses_content(monkeypatch):
    import asyncio

    from app.enrichment.sources import linkedin as li_mod

    async def fake_fallbacks(url: str):
        return (
            "Marina Dorokhova — Head of Product at HeadHunter. "
            "Skills: Product Management, P&L, Monetization. "
            "Open to Work.",
            "google_cache",
        )

    async def fake_json(prompt, system=None, tier="cheap"):
        return {
            "speaking_topics": ["монетизация продукта"],
            "extra_skills": ["Product Management", "P&L"],
            "job_search_status": "active",
        }

    monkeypatch.setattr(li_mod, "_fetch_with_fallbacks", fake_fallbacks)
    monkeypatch.setattr(li_mod.llm, "complete_json", fake_json)
    signals = asyncio.run(li_mod.LinkedInSource().fetch("https://linkedin.com/in/marina"))
    assert "P&L" in signals.extra_skills
    assert signals.job_search_status == "active"
    assert signals.speaking_topics
    assert any("google_cache" in n for n in signals.notes)


def test_looks_like_auth_wall():
    from app.enrichment.sources.linkedin import _looks_like_auth_wall

    assert _looks_like_auth_wall("Sign in Join now Authwall Join LinkedIn please sign in")
    assert not _looks_like_auth_wall(
        "Marina Dorokhova Head of Product. Experience at HeadHunter, Google. "
        "Skills: Product Management, P&L, Unit economics, Agile. " * 5
    )


def test_normalize_profile_url():
    from app.enrichment.sources.linkedin import _normalize_profile_url

    assert (
        _normalize_profile_url("https://www.linkedin.com/in/marina-dorokhova/?utm=1")
        == "https://www.linkedin.com/in/marina-dorokhova"
    )