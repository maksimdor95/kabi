"""Тесты парсинга CV (docs/services/profile.md). LLM замокан."""

import pytest

from app.services import cv_parser


def test_extract_text_txt(tmp_path):
    f = tmp_path / "cv.txt"
    f.write_text("Head of Product\nМосква", encoding="utf-8")
    assert "Head of Product" in cv_parser.extract_text(str(f))


def test_extract_text_unsupported(tmp_path):
    f = tmp_path / "cv.rtf"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        cv_parser.extract_text(str(f))


async def test_extract_profile_fields_maps_llm_output(monkeypatch):
    async def fake_complete_json(prompt, system=None, tier="primary"):
        return {
            "roles": ["Head of Product", "CPO"],
            "skills": ["Product Management", "SQL"],
            "location": "Москва",
            "languages": ["русский (родной)", "английский (свободно)"],
            "work_mode": "hybrid",
            "experience": [{"company": "HeadHunter", "role": "Business Unit Lead", "period": "2022–"}],
            "speaking_topics": ["монетизация продукта"],
            "goals": "вырасти до CPO",
            "salary_expectation": {"min": 500000, "currency": "RUB"},
        }

    monkeypatch.setattr(cv_parser.llm, "complete_json", fake_complete_json)

    draft = await cv_parser.extract_profile_fields("любой текст резюме")

    assert "CPO" in draft.roles
    assert draft.location == "Москва"
    assert draft.work_mode == "hybrid"
    assert "SQL" in draft.skills
    assert draft.experience[0]["company"] == "HeadHunter"
    assert draft.salary_expectation == {"min": 500000, "currency": "RUB"}


async def test_extract_profile_fields_empty_text_raises():
    with pytest.raises(ValueError):
        await cv_parser.extract_profile_fields("   ")
