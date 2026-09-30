"""Тесты карточки и меню по приоритету."""

from app.services.digest import DigestItem
from bot.keyboards import (
    MENU_DEADLINES,
    MENU_PITCH,
    MENU_PROFILE,
    MENU_SAVED,
    MENU_TODAY,
    format_card,
    format_source_label,
    main_menu_keyboard,
)


def test_parse_explain_structured():
    from app.services.cards import parse_explain

    essence, why = parse_explain(
        "СУТЬ: доменные планы + контроль исполнения\n"
        "ПОЧЕМУ:\n"
        "· вход в B2B LLM без смены трека\n"
        "- уровень ниже Head of Product — мост, не потолок\n"
        "* вилки нет — сначала созвон"
    )
    assert essence == "доменные планы + контроль исполнения"
    assert why is not None
    assert why.startswith("· вход в B2B LLM")
    assert why.count("\n") == 2
    assert "· вилки нет" in why


def test_source_labels():
    assert format_source_label("hh.ru") == "HeadHunter"
    assert format_source_label("tg_forproducts") == "Telegram · forproducts"
    assert format_source_label("career_avito") == "Авито · карьера"


def test_format_card_employer_and_snippet_no_source_accent():
    item = DigestItem(
        match_id="1",
        score=0.9,
        reason=(
            "СУТЬ: roadmap и метрики роста marketplace-команды\n"
            "ПОЧЕМУ:\n"
            "· уровень Head of Product — шаг к целевому контуру\n"
            "· marketplace-опыт из профиля цепляется к требованию\n"
            "· вилка есть — можно сразу считать fit по деньгам"
        ),
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
    assert "<blockquote expandable>" in text
    assert "<b>Суть:</b>" in text
    assert "roadmap и метрики" in text
    assert "Темы:" not in text
    assert "career_site" not in text
    assert "<b>Почему ты:</b>" in text
    assert "· уровень Head of Product" in text
    assert "📡" not in text  # источник не акцентируем


def test_format_card_legacy_prose_still_works():
    """Старые Match без СУТЬ/ПОЧЕМУ — суть из description, reason прозой."""
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
    assert "<blockquote expandable>" in text
    assert "<b>Суть:</b> ..." not in text
    assert "<b>Суть:</b> …" not in text
    assert "Проектировать" in text
    assert "<b>Почему ты:</b>" in text
    assert "Product Owner" in text


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
    # Sprint A: reply-меню укорочено — pitch/talks только командами.
    kb = main_menu_keyboard("job")
    labels = {btn.text for row in kb.keyboard for btn in row}
    assert MENU_TODAY in labels
    assert MENU_PITCH not in labels
    assert MENU_DEADLINES not in labels


def test_menu_talk_still_short():
    kb = main_menu_keyboard("talk")
    labels = {btn.text for row in kb.keyboard for btn in row}
    assert MENU_TODAY in labels
    assert MENU_SAVED in labels
    assert MENU_PROFILE in labels
    assert MENU_PITCH not in labels


def test_menu_both_short():
    kb = main_menu_keyboard("both")
    labels = {btn.text for row in kb.keyboard for btn in row}
    assert {MENU_TODAY, MENU_SAVED, MENU_PROFILE} <= labels
    assert MENU_PITCH not in labels
    assert MENU_DEADLINES not in labels
