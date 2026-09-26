"""Тесты устойчивости LLM-клиента к 429."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.llm import client as llm


class _FakeResp:
    def __init__(self, status_code: int, payload: dict | str):
        self.status_code = status_code
        if isinstance(payload, dict):
            self._json = payload
            self.text = str(payload)
        else:
            self._json = {}
            self.text = payload

    def json(self):
        return self._json


@pytest.mark.asyncio
async def test_post_retries_on_429_then_succeeds():
    calls = {"n": 0}

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, *a, **k):
            calls["n"] += 1
            if calls["n"] < 3:
                return _FakeResp(429, "quota limit exceed")
            return _FakeResp(200, {"ok": True})

    with (
        patch.object(llm, "_headers", return_value={"Authorization": "Api-Key x"}),
        patch.object(llm, "_POST_RETRY_BASE_SEC", 0.01),
        patch("httpx.AsyncClient", _FakeClient),
    ):
        data = await llm._post("embeddings", {"model": "m", "input": "hi"})

    assert data == {"ok": True}
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_post_does_not_retry_plain_400():
    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, *a, **k):
            return _FakeResp(400, "bad request")

    with (
        patch.object(llm, "_headers", return_value={"Authorization": "Api-Key x"}),
        patch("httpx.AsyncClient", _FakeClient),
    ):
        with pytest.raises(llm.LLMError, match="HTTP 400"):
            await llm._post("chat/completions", {"model": "m"})


@pytest.mark.asyncio
async def test_match_skips_when_profile_deleted():
    from app.services import matching as matching_service

    session = MagicMock()
    session.get = AsyncMock(return_value=None)
    profile = MagicMock()
    profile.id = "gone"

    out = await matching_service.match(session, profile, limit=3)
    assert out == []
