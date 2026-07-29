"""Тесты нормализации вакансий HH и SuperJob (без сети)."""

from app.ingestion.jobs import hh_connector, superjob_connector


def test_hh_normalize_basic():
    item = {
        "id": "12345",
        "name": "Head of Product",
        "employer": {"name": "Acme"},
        "area": {"name": "Москва"},
        "salary": {"from": 300000, "to": 400000, "currency": "RUR"},
        "alternate_url": "https://hh.ru/vacancy/12345",
        "schedule": {"id": "remote"},
        "snippet": {"responsibility": "Развивать продукт", "requirement": "5 лет в PM"},
        "published_at": "2026-07-20T10:00:00+0300",
    }
    draft = hh_connector.normalize_vacancy(item)
    assert draft is not None
    assert draft.title == "Head of Product"
    assert draft.org == "Acme"
    assert draft.location == "Москва"
    assert draft.remote is True
    assert draft.salary == {"min": 300000, "max": 400000, "currency": "RUB"}
    assert draft.source == "hh.ru"
    assert draft.external_id == "12345"
    assert "Развивать продукт" in draft.description


def test_hh_normalize_no_salary_and_office():
    item = {
        "id": "1",
        "name": "Product Manager",
        "employer": {"name": "Beta"},
        "area": {"name": "Москва"},
        "salary": None,
        "schedule": {"id": "fullDay"},
        "snippet": {},
    }
    draft = hh_connector.normalize_vacancy(item)
    assert draft is not None
    assert draft.salary is None
    assert draft.remote is False


def test_hh_normalize_skips_without_title():
    assert hh_connector.normalize_vacancy({"id": "1"}) is None


def test_superjob_normalize_basic():
    item = {
        "id": 777,
        "profession": "CPO",
        "firm_name": "Gamma",
        "town": {"title": "Москва"},
        "payment_from": 250000,
        "payment_to": 0,
        "currency": "rub",
        "work": "Стратегия продукта",
        "candidat": "Опыт CPO",
        "place_of_work": {"id": 2},
        "link": "https://superjob.ru/vakansii/777.html",
        "date_published": 1_700_000_000,
    }
    draft = superjob_connector.normalize_vacancy(item)
    assert draft is not None
    assert draft.title == "CPO"
    assert draft.org == "Gamma"
    assert draft.remote is True
    assert draft.salary == {"min": 250000, "max": None, "currency": "RUB"}
    assert draft.source == "superjob.ru"
    assert draft.external_id == "777"


def test_superjob_normalize_skips_without_company():
    assert superjob_connector.normalize_vacancy({"profession": "PM"}) is None
