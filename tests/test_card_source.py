"""Тесты карточки Sprint B0 и меню по приоритету."""

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


def test_parse_explain_structured_b0():
    from app.services.cards import parse_explain

    parts = parse_explain(
        "СУТЬ: оптимизация метрик и клиентский опыт\n"
        "О_КОМПАНИИ: fintech-команда в банке\n"
        "О_ПРОДУКТЕ: зарплатный сервис для физлиц\n"
        "ПОЧЕМУ:\n"
        "· роль Senior Product Owner совпадает с целевой\n"
        "- опыт FinTech из профиля цепляется к домену\n"
        "* метрики CR/MAU — прямое пересечение навыков"
    )
    assert parts.essence == "оптимизация метрик и клиентский опыт"
    assert parts.company == "fintech-команда в банке"
    assert parts.product == "зарплатный сервис для физлиц"
    assert parts.why is not None
    assert parts.why.startswith("· роль Senior Product Owner")
    assert parts.why.count("\n") == 2


def test_parse_explain_skips_empty_company_and_risk_bullet():
    from app.services.cards import parse_explain

    parts = parse_explain(
        "СУТЬ: запуск digital на зарубежных рынках\n"
        "О_КОМПАНИИ: —\n"
        "О_ПРОДУКТЕ: none\n"
        "ПОЧЕМУ:\n"
        "· upside (апсайд): влияние на международное направление\n"
        "· якорь — опыт полного цикла до PMF\n"
        "· нет информации о рисках или особенностях вакансии"
    )
    assert parts.company is None
    assert parts.product is None
    assert parts.why is not None
    assert "апсайд" not in parts.why.lower()
    assert "якорь" not in parts.why.lower()
    assert "upside" not in parts.why.lower()
    assert "риск" not in parts.why.lower()
    assert "влияние на международное" in parts.why
    assert "полного цикла до PMF" in parts.why
    assert parts.why.count("\n") == 1  # третий буллет отброшен


def test_source_labels():
    assert format_source_label("hh.ru") == "HeadHunter"
    assert format_source_label("tg_forproducts") == "Telegram · forproducts"
    assert format_source_label("career_avito") == "Авито · карьера"


def test_format_card_b0_layout():
    item = DigestItem(
        match_id="1",
        score=0.9,
        reason=(
            "СУТЬ: roadmap и метрики роста marketplace-команды\n"
            "О_КОМПАНИИ: крупный классифайд\n"
            "О_ПРОДУКТЕ: вертикаль товаров\n"
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
        link_label="Открыть вакансию →",
        description=(
            "Руководить продуктовой командой, формировать roadmap и метрики роста. "
            "Опыт в marketplace обязателен.\nТемы: career_site, avito"
        ),
    )
    text = format_card(item)
    assert "<b>🏢 Авито</b>" in text
    assert "📍 Москва · удалённо" in text
    assert "💰 от 500 000 RUB" in text
    assert "<b>Суть:</b> roadmap и метрики" in text
    assert "<b>О компании:</b> крупный классифайд" in text
    assert "<b>О продукте:</b> вертикаль товаров" in text
    # Суть снаружи цитаты; в цитате — описание источника
    essence_pos = text.index("<b>Суть:</b>")
    why_pos = text.index("<b>Почему ты:</b>")
    quote_pos = text.index("<blockquote expandable>")
    assert essence_pos < why_pos < quote_pos
    assert "· уровень Head of Product" in text
    assert "апсайд" not in text.lower()
    assert "Темы:" not in text
    assert "Открыть вакансию" in text


def test_format_card_omits_empty_company_product():
    item = DigestItem(
        match_id="3",
        score=0.7,
        reason=(
            "СУТЬ: продуктовый контур платежей\n"
            "О_КОМПАНИИ: —\n"
            "О_ПРОДУКТЕ: —\n"
            "ПОЧЕМУ:\n"
            "· роль Product Owner\n"
            "· опыт банковских продуктов"
        ),
        title="Product Owner",
        org="MAREE",
        location="Москва",
        remote=True,
        salary=None,
        url="https://example.com/x",
        source="hh.ru",
        description="Длинное описание обязанностей для цитаты. " * 8,
        link_label="Открыть вакансию →",
    )
    text = format_card(item)
    assert "О компании" not in text
    assert "О продукте" not in text
    assert "<b>Суть:</b>" in text
    assert "<blockquote expandable>" in text


def test_format_card_legacy_prose_still_works():
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
    assert "<b>Почему ты:</b>" in text
    assert "Product Owner" in text


def test_card_keyboard_draft_callback_and_favorites_label():
    from bot.keyboards import card_keyboard

    kb = card_keyboard("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    labels = {btn.text for row in kb.inline_keyboard for btn in row}
    assert "🔖 Избранное" in labels
    assert "✍️ Сопроводительное" in labels


def test_menu_job_hides_talks():
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
