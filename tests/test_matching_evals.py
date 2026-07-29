"""Тесты метрик matching eval (без LLM/БД)."""

from types import SimpleNamespace

from app.evals.metrics import (
    Thresholds,
    apply_thresholds,
    evaluate_explain_heuristic,
    evaluate_filters,
    evaluate_ranking,
    lexical_score,
    rank_lexical,
)
from app.evals.dataset import load_filter_cases, load_pool, load_profile_fixture, profile_from_fixture
from app.evals.metrics import EvalReport


def test_dataset_loads():
    profile = load_profile_fixture("marina_v1")
    assert "CPO" in profile["roles"]
    pool = load_pool("jobs_hh_sj_v1")
    assert len(pool) >= 50
    labels = {r["label"] for r in pool}
    assert labels >= {"relevant", "borderline", "noise"}
    cases = load_filter_cases("filter_negatives_v1")
    assert len(cases) >= 15


def test_lexical_prefers_cpo_title():
    profile = profile_from_fixture(load_profile_fixture())
    hop = SimpleNamespace(
        title="Head of Product",
        org="Acme",
        description="P&L стратегия продукта",
        location="Москва",
    )
    sales = SimpleNamespace(
        title="Руководитель направления продаж",
        org="Shop",
        description="KPI отдела продаж",
        location="Москва",
    )
    assert lexical_score(profile, hop) > lexical_score(profile, sales)


def test_evaluate_ranking_metrics_math():
    pool = [
        {"id": "a", "label": "relevant", "title": "CPO", "org": "A", "description": "product"},
        {"id": "b", "label": "noise", "title": "Sales", "org": "B", "description": "sales"},
        {"id": "c", "label": "borderline", "title": "PO", "org": "C", "description": "product"},
        {"id": "d", "label": "relevant", "title": "Head of Product", "org": "D", "description": "cpo"},
        {"id": "e", "label": "noise", "title": "Driver", "org": "E", "description": "x"},
        {"id": "f", "label": "relevant", "title": "Product Lead", "org": "F", "description": "lead"},
        {"id": "g", "label": "relevant", "title": "Директор по продукту", "org": "G", "description": "продукт"},
    ]
    ranked = [(r, 1.0 - i * 0.01) for i, r in enumerate(pool)]
    profile = SimpleNamespace(roles=["CPO"], skills=[], speaking_topics=[], location="Москва", work_mode="hybrid", salary_expectation={"min": 500000}, hard_nos={})
    result = evaluate_ranking(profile, pool, ranked=ranked, filtered_out=0)
    # top7 all; hard slots = relevant+noise = 6; relevant=4 → precision 4/6
    assert result.precision_at_n == 4 / 6
    assert result.noise_at_n == 2 / 7
    assert result.borderline_at_n == 1 / 7


def test_filters_gold_mostly_pass():
    profile = profile_from_fixture(load_profile_fixture())
    cases = load_filter_cases()
    result = evaluate_filters(profile, cases)
    assert result.accuracy >= 0.95


def test_full_pool_e1_e3_gate():
    profile = profile_from_fixture(load_profile_fixture())
    pool = load_pool()
    cases = load_filter_cases()
    ranked, filtered_out = rank_lexical(profile, pool, top_n=15)
    ranking = evaluate_ranking(
        profile, pool, ranked=ranked, filtered_out=filtered_out
    )
    filters = evaluate_filters(profile, cases)
    report = apply_thresholds(
        EvalReport(
            pool_version="jobs_hh_sj_v1",
            profile_id="marina_v1",
            ranking=ranking,
            filters=filters,
        )
    )
    assert report.passed, report.summary()


def test_explain_heuristic_flags_fallback_and_invention():
    profile = profile_from_fixture(load_profile_fixture())
    row = {
        "id": "x",
        "label": "relevant",
        "title": "CPO",
        "org": "Acme",
        "description": "продукт",
    }
    good = (
        "Роль CPO совпадает с целевой; Acme и продукт пересекаются со стратегией и P&L."
    )
    bad_fallback = "Совпадение по роли и ключевым навыкам."
    invented = "Ты работал в SpaceX и получал 9999999 рублей."
    result = evaluate_explain_heuristic(
        profile,
        [(row, good), (row, bad_fallback), (row, invented)],
    )
    assert result.scores[0].total >= 5
    assert result.scores[1].r2 == 0
    assert result.scores[2].r1 == 0


def test_vector_rank_uses_cosine_cache():
    from app.evals.embeddings import rank_vector

    profile = profile_from_fixture(load_profile_fixture())
    pool = [
        {
            "id": "good",
            "label": "relevant",
            "title": "CPO",
            "org": "A",
            "description": "x",
            "remote": True,
            "salary": {"min": 600000, "currency": "RUB"},
        },
        {
            "id": "bad",
            "label": "noise",
            "title": "Sales",
            "org": "B",
            "description": "y",
            "remote": True,
            "salary": {"min": 600000, "currency": "RUB"},
        },
    ]
    # profile ~ [1,0], good aligned, bad orthogonal
    cache = {
        "profile_embedding": [1.0, 0.0],
        "items": {"good": [0.9, 0.1], "bad": [0.0, 1.0]},
    }
    ranked, _ = rank_vector(profile, pool, cache, top_n=2)
    assert ranked[0][0]["id"] == "good"
    assert ranked[0][1] > ranked[1][1]


def test_human_gold_heuristic_r1_agreement():
    """Heuristic калибруется на human gold по R1 (≥0.7 до LM-judge)."""
    from app.evals.judge import agreement_r1, gold_to_scores, load_judge_gold

    profile = profile_from_fixture(load_profile_fixture())
    gold = load_judge_gold()
    human = gold_to_scores(gold)
    pairs = [
        (
            {
                "id": r["id"],
                "title": r.get("title"),
                "org": r.get("org"),
                "description": r.get("description"),
                "label": r.get("label"),
            },
            r["reason"],
        )
        for r in gold
    ]
    pred = evaluate_explain_heuristic(profile, pairs).scores
    agr = agreement_r1(human, pred)
    assert agr >= 0.7, f"heuristic R1 agreement={agr}"


def test_parse_judge_payload_tolerates_broken_brief():
    from app.evals.judge import _parse_judge_payload

    raw = '{"r1":2,"r2":1,"r3":2,"r4":2,"brief":"текст с "кавычками" внутри"}'
    data = _parse_judge_payload(raw)
    assert data["r1"] == 2
    assert data["r2"] == 1
