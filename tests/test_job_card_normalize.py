"""Нормализация title/org для карточек вакансий (без отсечения)."""

from app.ingestion.normalize_job import (
    clean_job_title,
    display_title,
    guess_org_from_title,
    normalize_job_draft,
)
from app.ingestion.schemas import OpportunityDraft
from app.services.digest import DigestItem
from bot.keyboards import format_card

_FIZIKL = (
    "Менеджер продукта Физикл — это экосистема, которая помогает людям менять "
    "образ жизни системно: питание, тренировки, привычки и здоровье. Наши "
    "продуктовые направления: — FoodTracker — управление питани"
)


def test_clean_fizikl_title():
    title = clean_job_title(_FIZIKL)
    assert title == "Менеджер продукта"
    assert "экосистема" not in title
    assert "питани" not in title
    org = guess_org_from_title(_FIZIKL)
    assert org == "Физикл"


def test_normalize_draft_keeps_vacancy():
    d = OpportunityDraft(
        type="job",
        title=_FIZIKL,
        description=_FIZIKL,
        source="tg_forproducts",
        external_id="1",
    )
    normalize_job_draft(d)
    assert d.title == "Менеджер продукта"
    assert d.org == "Физикл"
    assert d.description
    assert "экосистема" in (d.description or "")


def test_format_card_fizikl_readable():
    item = DigestItem(
        match_id="1",
        score=0.9,
        reason="Опыт Head of Product",
        title=_FIZIKL,
        org=None,
        location=None,
        remote=True,
        salary=None,
        url="https://example.com",
        source="tg_x",
        description=_FIZIKL,
    )
    text = format_card(item)
    assert "<b>Менеджер продукта</b>" in text
    assert "<b>🏢 Физикл</b>" in text
    assert "экосистема" in text  # в Сути, не в title
    # title не должен быть длинным питчем
    assert "FoodTracker" not in text.split("<b>Суть:</b>")[0]


def test_display_title_short_roles_untouched():
    assert display_title("Head of Product", org="Авито") == "Head of Product"
    assert clean_job_title("Руководитель цифрового продукта") == (
        "Руководитель цифрового продукта"
    )
