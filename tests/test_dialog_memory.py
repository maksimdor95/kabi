"""Unit-тесты dialog_memory (in-memory fallback)."""

from uuid import uuid4

import pytest

from app.services import dialog_memory


@pytest.fixture(autouse=True)
def _reset_memory():
    dialog_memory.reset_for_tests()
    # Форсируем fallback без Redis в тестах
    dialog_memory._redis_failed = True
    yield
    dialog_memory.reset_for_tests()


@pytest.mark.asyncio
async def test_append_and_get_window():
    uid = uuid4()
    await dialog_memory.append_turn(uid, "привет", "здравствуй")
    await dialog_memory.append_turn(uid, "как дела", "по делу")
    hist = await dialog_memory.get_history(uid)
    assert hist == [
        {"role": "user", "content": "привет"},
        {"role": "assistant", "content": "здравствуй"},
        {"role": "user", "content": "как дела"},
        {"role": "assistant", "content": "по делу"},
    ]


@pytest.mark.asyncio
async def test_window_trims():
    uid = uuid4()
    # WINDOW=12 сообщений → 6 пар; пишем 8 пар → останется 12 msgs
    for i in range(8):
        await dialog_memory.append_turn(uid, f"u{i}", f"a{i}")
    hist = await dialog_memory.get_history(uid)
    assert len(hist) == dialog_memory.WINDOW
    assert hist[0]["content"] == "u2"
    assert hist[-1]["content"] == "a7"


@pytest.mark.asyncio
async def test_clear():
    uid = uuid4()
    await dialog_memory.append_turn(uid, "x", "y")
    await dialog_memory.clear(uid)
    assert await dialog_memory.get_history(uid) == []
