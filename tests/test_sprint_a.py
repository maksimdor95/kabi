"""Sprint A: парсеры новых шагов онбординга."""

from app.services.onboarding import parse_answer
from app.services.dialogue_agent import apply_level_to_roles, roles_need_level
from app.services.bootstrap import text_looks_like_profile_seed
from app.services.schedule import digest_limit_for, normalize_schedule, parse_schedule_command


def test_parse_confirm_roles_ok_keeps_empty_patch():
    r = parse_answer("confirm_roles", "Ок, роли верные")
    assert r.ok and r.patch == {}


def test_parse_confirm_roles_rewrite():
    r = parse_answer("confirm_roles", "Head of Product, CPO")
    assert r.ok and r.patch["roles"] == ["Head of Product", "CPO"]


def test_parse_focus_aim_chip_and_skip():
    r = parse_answer("focus_aim", "MedTech")
    assert r.ok and r.patch["goals"] == "MedTech"
    r2 = parse_answer("focus_aim", "Пока без фокуса")
    assert r2.ok and r2.patch["goals"] is None


def test_parse_level():
    r = parse_answer("level", "Senior")
    assert r.ok and r.patch["_level"] == "Senior"


def test_roles_need_level():
    assert roles_need_level(["Product Manager"]) is True
    assert roles_need_level(["Senior Product Manager"]) is False


def test_apply_level_to_roles():
    assert apply_level_to_roles(["Product Manager"], "Senior") == [
        "Senior Product Manager"
    ]


def test_text_seed_heuristic():
    assert text_looks_like_profile_seed("ищу роль senior product manager 8 лет")
    assert text_looks_like_profile_seed("Продукт оунер в СберБанке")
    assert text_looks_like_profile_seed(
        "работаю в fintech пять лет, сейчас смотрю на CPO-трек"
    )
    assert not text_looks_like_profile_seed("привет")
    assert not text_looks_like_profile_seed("2")
    assert not text_looks_like_profile_seed("Текст")


def test_digest_limit_default_and_command():
    s = normalize_schedule(None)
    assert s["digest_limit"] == 3
    assert s["watch_batch_limit"] == 3
    updated = parse_schedule_command("лимит 5", s)
    assert updated is not None
    assert updated["digest_limit"] == 5
    assert digest_limit_for(type("P", (), {"digest_schedule": updated})()) == 5
