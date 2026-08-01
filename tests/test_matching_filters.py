"""Тесты хард-фильтров мэтчинга и dedup ингестии (без БД/сети)."""

from types import SimpleNamespace

from app.ingestion.keywords import derive_hh_area, derive_keywords
from app.ingestion.runner import _dedup_drafts
from app.ingestion.schemas import OpportunityDraft
from app.services.matching import is_evergreen_pitch, passes_hard_filters


def _profile(**kw):
    base = {
        "work_mode": "hybrid",
        "salary_expectation": {"min": 300000, "currency": "RUB"},
        "hard_nos": {},
        "roles": ["Head of Product", "CPO"],
        "skills": ["product", "roadmap"],
        "speaking_topics": ["product management"],
        "location": "Москва",
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _opp(**kw):
    base = {
        "type": "job",
        "title": "Head of Product",
        "org": "Acme",
        "description": "Отличная роль",
        "remote": True,
        "salary": {"min": 350000, "max": 450000, "currency": "RUB"},
        "deadline": None,
        "meta": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_salary_below_min_rejected():
    opp = _opp(salary={"min": 100000, "max": 200000, "currency": "RUB"})
    assert passes_hard_filters(opp, _profile()) is False


def test_salary_unknown_kept():
    opp = _opp(salary=None)
    assert passes_hard_filters(opp, _profile()) is True


def test_remote_only_rejects_office():
    opp = _opp(remote=False)
    assert passes_hard_filters(opp, _profile(work_mode="remote")) is False


def test_remote_only_keeps_remote():
    opp = _opp(remote=True)
    assert passes_hard_filters(opp, _profile(work_mode="remote")) is True


def test_hard_no_term_rejected():
    opp = _opp(org="Casino Corp")
    profile = _profile(hard_nos={"industries": ["casino", "гэмблинг"]})
    assert passes_hard_filters(opp, profile) is False


def test_tech_title_rejected_for_product_profile():
    opp = _opp(title="Senior Python Developer", description="Писать сервисы на FastAPI")
    assert passes_hard_filters(opp, _profile()) is False


def test_project_manager_without_product_rejected():
    opp = _opp(
        title="Менеджер проектов, Контент",
        description="Ведение контент-проектов и сроков",
    )
    assert passes_hard_filters(opp, _profile()) is False


def test_product_lead_kept():
    opp = _opp(title="Product Lead / Head of Product", description="Владение продуктом")
    assert passes_hard_filters(opp, _profile()) is True


def test_product_designer_rejected_for_cpo():
    opp = _opp(
        title="Product Designer",
        description="Дизайн продукта, UX research, Figma",
    )
    assert passes_hard_filters(opp, _profile()) is False


def test_product_analyst_rejected_for_cpo():
    opp = _opp(
        title="Продуктовый аналитик",
        description="Метрики продукта, SQL, A/B",
    )
    assert passes_hard_filters(opp, _profile()) is False


def test_designer_without_product_rejected():
    opp = _opp(title="UX-дизайнер", description="Интерфейсы мобильных приложений")
    assert passes_hard_filters(opp, _profile()) is False


def test_cpo_kept():
    opp = _opp(title="Директор по продукту (CPO)", description="Стратегия продукта")
    assert passes_hard_filters(opp, _profile()) is True


def test_talk_closed_rejected():
    opp = _opp(
        type="talk",
        title="ProductSense — доклад",
        meta={"status": "closed", "topics": ["product"]},
        deadline=None,
    )
    assert passes_hard_filters(opp, _profile(speaking_topics=["product"], skills=[], roles=["CPO"])) is False


def test_talk_watch_rejected():
    opp = _opp(
        type="talk",
        title="Epic Growth — доклад",
        meta={"status": "watch", "topics": ["growth", "продукт"]},
        deadline=None,
    )
    assert passes_hard_filters(
        opp, _profile(speaking_topics=["продукт"], skills=[], roles=["CPO"])
    ) is False


def test_talk_topic_overlap_required():
    opp = _opp(
        type="talk",
        title="Forbes — интервью",
        meta={"status": "open", "topics": ["карьера", "образование"]},
        deadline=None,
    )
    # Product Owner без пересечения с «карьера/образование» токенами — отсев.
    # (роли "Product Owner" не пересекаются с topics карьера/образование)
    profile = _profile(
        speaking_topics=["B2B SaaS", "PLG"],
        skills=["SQL"],
        roles=["Product Owner"],
    )
    assert passes_hard_filters(opp, profile) is False


def test_talk_topic_overlap_keeps_match():
    opp = _opp(
        type="talk",
        title="vc.ru — колонка",
        meta={"status": "open", "topics": ["product", "навыки", "skill-based"]},
        deadline=None,
    )
    profile = _profile(
        speaking_topics=["skill-based hiring"],
        skills=["product"],
        roles=["Head of Product"],
    )
    assert passes_hard_filters(opp, profile) is True


def test_talk_topic_soft_morphology_keeps_match():
    """«продукт» профиля пересекается с «управлением IT-продуктом» площадки."""
    opp = _opp(
        type="talk",
        title="Skillfactory — воркшоп",
        meta={"status": "open", "topics": ["управление IT-продуктом", "EdTech"]},
        deadline=None,
    )
    profile = _profile(
        speaking_topics=["продукт"],
        skills=[],
        roles=["Product Owner"],
    )
    assert passes_hard_filters(opp, profile) is True


def test_is_evergreen_pitch_media_without_deadline():
    media = _opp(
        type="talk",
        title="РБК — колонка",
        deadline=None,
        meta={"kind": "media", "how": "column", "topics": ["карьера"]},
    )
    assert is_evergreen_pitch(media) is True


def test_is_evergreen_pitch_rejects_cfp_with_deadline():
    from datetime import datetime, timezone

    cfp = _opp(
        type="talk",
        title="ProductSense — CFP",
        deadline=datetime(2026, 9, 1, tzinfo=timezone.utc),
        meta={"kind": "conference", "how": "cfp_talk", "topics": ["product"]},
    )
    assert is_evergreen_pitch(cfp) is False


def test_is_evergreen_pitch_rejects_conference_kind():
    conf = _opp(
        type="talk",
        title="Epic Growth",
        deadline=None,
        meta={"kind": "conference", "how": "cfp_talk", "topics": ["growth"]},
    )
    assert is_evergreen_pitch(conf) is False


def test_derive_keywords_dedup_preserves_order():
    profile = SimpleNamespace(roles=["Head of Product", "head of product", "CPO"], location=None)
    assert derive_keywords(profile) == ["Head of Product", "CPO"]


def test_derive_hh_area_defaults_moscow():
    assert derive_hh_area(SimpleNamespace(location=None)) == 1
    assert derive_hh_area(SimpleNamespace(location="Санкт-Петербург")) == 2
    assert derive_hh_area(SimpleNamespace(location="Москва")) == 1


def test_dedup_drafts_by_source_and_id():
    a = OpportunityDraft(type="job", title="A", source="hh.ru", external_id="1")
    b = OpportunityDraft(type="job", title="A dup", source="hh.ru", external_id="1")
    c = OpportunityDraft(type="job", title="B", source="hh.ru", external_id="2")
    unique = _dedup_drafts([a, b, c])
    assert len(unique) == 2
