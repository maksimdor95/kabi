"""Тесты роутера advisor tools и сборки messages советника (M9)."""

from types import SimpleNamespace
from uuid import uuid4

from app.services import advisor_tools
from app.services.dialogue_agent import _MANAGER_PERSONA, _build_advisor_messages


def test_select_tools_profile():
    assert advisor_tools.select_tools("Что ты обо мне знаешь?") == ["get_profile"]
    assert "get_profile" in advisor_tools.select_tools("покажи мой профиль")


def test_select_tools_jobs_and_schedule():
    assert advisor_tools.select_tools("какие вакансии есть?") == ["get_job_snapshot"]
    assert advisor_tools.select_tools("когда присылаешь подборки?") == ["get_schedule"]


def test_select_tools_talks_not_mass_media_keyword_alone():
    # «подкаст» тянет talk snapshot — ок; роутер не зовёт jobs
    assert advisor_tools.select_tools("куда выступить на конференции?") == [
        "get_talk_snapshot"
    ]


def test_select_tools_multi():
    tools = advisor_tools.select_tools("что в профиле и какое расписание?")
    assert tools == ["get_profile", "get_schedule"]


def test_select_tools_empty_for_chitchat():
    assert advisor_tools.select_tools("спасибо, ты молодец") == []


def test_persona_forbids_day_planner_and_tv():
    low = _MANAGER_PERSONA.lower()
    assert "планёр" in low or "to-do" in low or "todo" in low
    assert "тв" in low or "масс-медиа" in low or "нтв" in low
    assert "не выдумывай" in low


def test_eval_pool_expect_tools_contract():
    """Контракт evals/dialogue: expect_tools совпадает с роутером."""
    import json
    from pathlib import Path

    path = Path("evals/dialogue/pools/advisor_m9_v1.jsonl")
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        got = advisor_tools.select_tools(row["user"])
        assert got == row["expect_tools"], (row["id"], got, row["expect_tools"])


def test_build_advisor_messages_includes_history_and_tools():
    profile = SimpleNamespace(
        user_id=uuid4(),
        roles=["Product Manager"],
        skills=["B2B"],
        location="Москва",
        work_mode="hybrid",
        speaking_topics=[],
        goals="рост",
    )
    # profile_to_text uses real Profile fields — monkey via duck typing fails.
    # Используем минимальный объект с нужными атрибутами как у Profile.
    hist = [
        {"role": "user", "content": "привет"},
        {"role": "assistant", "content": "слушаю"},
    ]
    messages = _build_advisor_messages(
        profile=profile,  # type: ignore[arg-type]
        history=hist,
        tool_context="### Расписание\nмониторинг",
        user_text="когда пишешь?",
    )
    assert messages[0]["role"] == "system"
    assert "мониторинг" in messages[0]["content"]
    assert messages[1] == hist[0]
    assert messages[2] == hist[1]
    assert messages[-1] == {"role": "user", "content": "когда пишешь?"}
