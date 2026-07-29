"""Тесты контракта готовности профиля (docs/services/profile.md)."""

from app.domain.profile import Profile, SalaryExpectation


def _filled() -> Profile:
    p = Profile(user_id="u")
    p.roles = ["CPO"]
    p.location = "Москва"
    p.work_mode = "hybrid"
    p.skills = ["Product Management"]
    p.salary_expectation = SalaryExpectation(min=500000)
    p.enrichment_consent = True
    return p


def test_empty_profile_not_ready():
    assert Profile(user_id="u").is_ready_for_matching() is False


def test_filled_profile_ready():
    assert _filled().is_ready_for_matching() is True


def test_salary_is_mandatory():
    p = _filled()
    p.salary_expectation = None
    assert p.is_ready_for_matching() is False


def test_consent_is_mandatory():
    p = _filled()
    p.enrichment_consent = False
    assert p.is_ready_for_matching() is False


def test_default_priorities_is_both():
    assert Profile(user_id="u").priorities == "both"
