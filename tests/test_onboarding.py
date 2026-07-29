"""Тесты детерминированных парсеров онбординга (docs/services/dialogue-agent.md)."""

from app.services.onboarding import interpret_answer, parse_answer


def test_priorities_requires_clear_choice():
    assert parse_answer("priorities", "пока не знаю").ok is False
    assert interpret_answer("priorities", "и работа, и выступления")["priorities"] == "both"


def test_priorities_job_and_talk():
    assert interpret_answer("priorities", "Работа")["priorities"] == "job"
    assert interpret_answer("priorities", "ищу работу")["priorities"] == "job"
    assert interpret_answer("priorities", "Выступления")["priorities"] == "talk"
    assert interpret_answer("priorities", "Оба")["priorities"] == "both"


def test_salary_variants():
    assert interpret_answer("salary", "от 500 000 руб")["salary_expectation"] == {
        "min": 500000,
        "currency": "RUB",
    }
    assert interpret_answer("salary", "$8000 в месяц")["salary_expectation"] == {
        "min": 8000,
        "currency": "USD",
    }
    assert interpret_answer("salary", "500к")["salary_expectation"] == {
        "min": 500000,
        "currency": "RUB",
    }
    assert parse_answer("salary", "не готова сказать").ok is False
    assert parse_answer("salary", "херня").ok is False


def test_status():
    assert interpret_answer("status", "Активно")["job_search_status"] == "active"
    assert interpret_answer("status", "Только топ")["job_search_status"] == "top_only"
    assert interpret_answer("status", "Присматриваюсь")["job_search_status"] == "passive"
    assert parse_answer("status", "asdf").ok is False


def test_consent_and_links():
    patch = interpret_answer(
        "consent_links", "ок, вот https://hh.ru/resume/123 и https://linkedin.com/in/x"
    )
    assert patch["enrichment_consent"] is True
    assert len(patch["source_links"]["links"]) == 2

    assert interpret_answer("consent_links", "Пропустить")["enrichment_consent"] is True
    assert interpret_answer("consent_links", "Пропустить")["source_links"] == {"links": []}
    assert interpret_answer("consent_links", "пропустит")["source_links"] == {"links": []}
    assert interpret_answer("consent_links", "нет")["enrichment_consent"] is False
    assert interpret_answer("consent_links", "нет")["source_links"] == {"links": []}


def test_consent_accepts_www_without_scheme():
    from app.services.onboarding import extract_urls, filter_useful_links

    urls = extract_urls("www.linkedin.com/in/максим-дорохов-3b37a5272")
    assert urls == ["https://www.linkedin.com/in/максим-дорохов-3b37a5272"]
    useful, junk = filter_useful_links(urls)
    assert useful and not junk

    patch = interpret_answer(
        "consent_links", "www.linkedin.com/in/maxim-dorokhov"
    )
    assert patch["enrichment_consent"] is True
    assert patch["source_links"]["links"] == [
        "https://www.linkedin.com/in/maxim-dorokhov"
    ]


def test_linkedin_feed_is_junk():
    from app.services.onboarding import filter_useful_links, extract_urls

    useful, junk = filter_useful_links(
        extract_urls("https://www.linkedin.com/feed/")
    )
    assert useful == []
    assert junk


def test_hard_nos():
    assert interpret_answer("hard_nos", "Нет красных флагов")["hard_nos"] == {}
    assert interpret_answer("hard_nos", "нет")["hard_nos"] == {}
    assert interpret_answer("hard_nos", "не хочу в гемблинг")["hard_nos"]["raw"]


def test_availability_requires_clear():
    assert parse_answer("availability", "да").ok is False
    assert parse_answer("availability", "нет").ok is False
    ok = parse_answer("availability", "Занят(а), через 4 нед.")
    assert ok.ok
    assert ok.patch["availability"]["busy"] is True
    assert ok.patch["availability"]["weeks"] == 4
    free = parse_answer("availability", "Свободен(на), сразу")
    assert free.ok
    assert free.patch["availability"]["busy"] is False
    assert free.patch["availability"]["weeks"] == 0
    home = parse_answer("availability", "дома, сплю")
    assert home.ok
    assert home.patch["availability"]["busy"] is False


def test_priorities_short_answers():
    assert interpret_answer("priorities", "о")["priorities"] == "both"
    assert interpret_answer("priorities", "р")["priorities"] == "job"
    assert interpret_answer("priorities", "в")["priorities"] == "talk"


def test_restart_phrase():
    from app.services.onboarding import is_restart_request

    assert is_restart_request("начать заново")
    assert not is_restart_request("работа")


def test_neutral_availability_question():
    # availability убран из STEPS (не влияет на мэтчинг); парсер остаётся для совместимости
    from app.services.onboarding import STEPS

    keys = [s.key for s in STEPS]
    assert "availability" not in keys
    assert "status" not in keys


def test_priorities_question_explains_choices():
    from app.services.onboarding import STEPS

    q = next(s.question for s in STEPS if s.key == "priorities")
    assert "Работа" in q
    assert "Выступления" in q
    assert "Оба" in q
    assert "ваканси" in q.lower()


def test_skip_salary_when_known():
    from app.db.models import Profile
    from app.services.dialogue_agent import _should_skip_step

    p = Profile(user_id=__import__("uuid").uuid4())
    p.salary_expectation = {"min": 500000, "currency": "RUB"}
    assert _should_skip_step(p, "salary") is True
    p.salary_expectation = None
    assert _should_skip_step(p, "salary") is False
