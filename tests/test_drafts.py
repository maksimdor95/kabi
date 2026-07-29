"""Тесты черновиков drafts (мок LLM)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import drafts as drafts_service


@pytest.mark.asyncio
async def test_draft_application_prompt_has_profile_and_opp(monkeypatch):
    captured: dict = {}

    async def fake_complete(prompt, system=None, tier="primary", **kwargs):
        captured["prompt"] = prompt
        captured["system"] = system
        return "Черновик отклика.\n— черновик, отправь сам после правок"

    monkeypatch.setattr(drafts_service.llm, "complete", fake_complete)

    profile = SimpleNamespace(
        roles=["Head of Product", "CPO"],
        skills=["Product Management"],
        location="Москва",
        work_mode="hybrid",
        speaking_topics=[],
        goals="рост продукта",
    )
    # profile_to_text expects ORM-like attrs — patch it
    monkeypatch.setattr(
        drafts_service,
        "profile_to_text",
        lambda p: "Head of Product CPO\nProduct Management\nМосква",
    )
    opp = SimpleNamespace(
        id="o1",
        type="job",
        title="Product Lead FinTech",
        org="Банк Тест",
        location="Москва",
        remote=False,
        description="Управление продуктом",
        deadline=None,
        url="https://example.com/job",
    )

    text = await drafts_service.draft_application(profile, opp)
    assert "черновик" in text.lower()
    assert "Head of Product" in captured["prompt"]
    assert "Product Lead FinTech" in captured["prompt"]
    assert "не выдумывай" in (captured["system"] or "").lower() or "Только факты" in (
        captured["system"] or ""
    )


@pytest.mark.asyncio
async def test_draft_for_opportunity_routes_talk(monkeypatch):
    called = {"cfp": False, "app": False}

    async def fake_cfp(profile, opp):
        called["cfp"] = True
        return "cfp-draft"

    async def fake_app(profile, opp):
        called["app"] = True
        return "app-draft"

    monkeypatch.setattr(drafts_service, "draft_cfp_pitch", fake_cfp)
    monkeypatch.setattr(drafts_service, "draft_application", fake_app)

    profile = SimpleNamespace()
    talk = SimpleNamespace(id="t1", type="talk")
    job = SimpleNamespace(id="j1", type="job")

    assert await drafts_service.draft_for_opportunity(profile, talk) == "cfp-draft"
    assert called["cfp"] and not called["app"]

    called["cfp"] = False
    assert await drafts_service.draft_for_opportunity(profile, job) == "app-draft"
    assert called["app"]
