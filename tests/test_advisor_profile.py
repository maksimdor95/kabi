"""Тесты записи профиля из чата и live-tools (M9 polish)."""

from app.services.advisor_profile import extract_chat_profile_update
from app.services import advisor_tools


def test_salary_update_explicit():
    u = extract_chat_profile_update("Обнови зарплату: ожидания от 600к руб")
    assert u.patch["salary_expectation"]["min"] == 600000
    assert u.patch["salary_expectation"]["currency"] == "RUB"
    assert u.notes


def test_salary_not_from_chitchat():
    u = extract_chat_profile_update("спасибо, ты молодец")
    assert u.patch == {}


def test_hard_nos_update():
    u = extract_chat_profile_update("Не предлагай банки и гемблу")
    assert u.patch["hard_nos"]["raw"]
    assert "банк" in u.patch["hard_nos"]["raw"].lower() or "гембл" in u.patch["hard_nos"]["raw"].lower()


def test_priority_update():
    u = extract_chat_profile_update("Приоритет: хочу только работу")
    assert u.patch.get("priorities") == "job"


def test_location_update():
    u = extract_chat_profile_update("Живу в Казани сейчас")
    assert u.patch.get("location") == "Казани"


def test_refresh_jobs_beats_snapshot():
    assert advisor_tools.select_tools("Найди вакансии пожалуйста") == ["refresh_jobs"]
    assert advisor_tools.select_tools("Какие вакансии сейчас есть?") == ["get_job_snapshot"]


def test_refresh_talks():
    assert advisor_tools.select_tools("Найди конференции со сроком подачи") == [
        "refresh_talks"
    ]
