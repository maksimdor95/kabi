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
            "Опыт в marketplace обязателен.\nТемы: career_site, avito"
        ),
    )
    text = format_card(item)
    assert "<b>🏢 Авито</b>" in text
    assert "💰 от 500 000 RUB" in text
    assert "<b>Суть:</b>" in text
    assert "roadmap" in text
    assert "Темы:" not in text
    assert "career_site" not in text
    assert "<b>Почему ты:</b>" in text
    assert "📡" not in text  # источник не акцентируем


def test_format_card_truncates_with_ellipsis():
    long_desc = (
        "Проектировать сквозной пользовательский путь: от входа в раздел до перехода. "
        "Опыт работы Product Manager от 3 лет. "
        "Опыт развития мобильных или крупных цифровых продуктов. "
        "Умение самостоятельно формировать продуктовую стратегию и roadmap на год. "
        "Работать со стейкхолдерами и приоритизировать бэклог по бизнес-ценности."
    )
    long_reason = (
        "Опыт работы в роли Product Owner и руководителя проектов более пяти лет, "
        "включая запуск продуктов с нуля и работу с метриками, полностью соответствует "
        "требованиям вакансии Product Manager в крупной компании и ожиданиям команды."
    )
    item = DigestItem(
        match_id="2",
        score=0.8,
        reason=long_reason,
        title="Product manager",
        org="РСХБ-Интех",
        location="Москва",
        remote=False,
        salary=None,
        url="https://example.com/job",
        source="hh.ru",
        description="..." + long_desc,
    )
    text = format_card(item)
    assert text.count("…") >= 1
    assert "<b>Суть:</b> ..." not in text  # не начинаем с трёх точек
    assert "<b>Суть:</b> …" not in text
    assert "Проектировать" in text
    why = text.split("<b>Почему ты:</b> ", 1)[1].split("\n\n", 1)[0]
    assert why.endswith("…")
    assert len(why) <= 230


def test_card_keyboard_draft_callback_and_favorites_label():
    from bot.keyboards import card_keyboard

    kb = card_keyboard("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    labels = {btn.text for row in kb.inline_keyboard for btn in row}
    assert "🔖 Избранное" in labels
    assert "✍️ Сопроводительное" in labels
    draft = [
        btn
        for row in kb.inline_keyboard
        for btn in row
        if btn.text == "✍️ Сопроводительное"
    ][0]
    assert draft.callback_data.startswith("draft:")
    assert not draft.callback_data.startswith("fb:")


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
