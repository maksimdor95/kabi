"""Тесты карточки и меню по приоритету."""

from app.services.digest import DigestItem
from bot.keyboards import (
    MENU_DEADLINES,
    MENU_PITCH,
    MENU_TODAY,
    format_card,
    format_source_label,
    main_menu_keyboard,
)


def test_source_labels():
    assert format_source_label("hh.ru") == "HeadHunter"
    assert format_source_label("tg_forproducts") == "Telegram · forproducts"
    assert format_source_label("career_avito") == "Авито · карьера"


def test_format_card_employer_and_snippet_no_source_accent():
    item = DigestItem(
        match_id="1",
        score=0.9,
        reason="Подходит по роли CPO",
        title="Head of Product",
        org="Авито",
        location="Москва",
        remote=True,
        salary={"min": 500000, "currency": "RUB"},
        url="https://example.com",
        source="career_avito",
        opp_type="job",
        description=(
            "Руководить продуктовой командой, формировать roadmap и метрики роста. "
            "Опыт в marketplace обязателен."
        ),
    )
    text = format_card(item)
    assert "<b>🏢 Авито</b>" in text
    assert "💰 от 500 000 RUB" in text
    assert "<b>Суть:</b>" in text
    assert "roadmap" in text
    assert "<b>Почему ты:</b>" in text
    assert "📡" not in text  # источник не акцентируем


def test_menu_job_hides_talks():
    kb = main_menu_keyboard("job")
    labels = {btn.text for row in kb.keyboard for btn in row}
    assert MENU_TODAY in labels
    assert MENU_PITCH not in labels
    assert MENU_DEADLINES not in labels


def test_menu_talk_hides_jobs():
    kb = main_menu_keyboard("talk")
    labels = {btn.text for row in kb.keyboard for btn in row}
    assert MENU_TODAY not in labels
    assert MENU_PITCH in labels
    assert MENU_DEADLINES in labels


def test_menu_both_has_all():
    kb = main_menu_keyboard("both")
    labels = {btn.text for row in kb.keyboard for btn in row}
    assert {MENU_TODAY, MENU_PITCH, MENU_DEADLINES} <= labels
