"""Тесты подписи источника на карточке."""

from app.services.digest import DigestItem
from bot.keyboards import format_card, format_source_label


def test_source_labels():
    assert format_source_label("hh.ru") == "HeadHunter"
    assert format_source_label("superjob.ru") == "SuperJob"
    assert format_source_label("tg_forproducts") == "Telegram · forproducts"
    assert format_source_label("career_avito") == "Авито · карьера"
    assert format_source_label(None) is None


def test_format_card_shows_source():
    item = DigestItem(
        match_id="1",
        score=0.9,
        reason="Подходит по роли",
        title="Product Owner",
        org="Авито",
        location="Москва",
        remote=False,
        salary=None,
        url="https://example.com",
        source="career_avito",
        opp_type="job",
    )
    text = format_card(item)
    assert "📡 Авито · карьера" in text
    assert "Авито" in text  # org
    assert "Product Owner" in text
