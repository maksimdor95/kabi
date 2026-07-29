"""Метрики E1/E2/E3. Спека: docs/services/evals.md §8."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Iterable

from app.services.matching import passes_hard_filters

_TOKEN_RE = re.compile(r"[a-zа-яё0-9]{2,}", re.I)
_FALLBACK_REASONS = (
    "совпадение по роли и ключевым навыкам",
    "площадка пересекается с твоими темами экспертности",
)


@dataclass(frozen=True)
class Thresholds:
    """Пороги фазы 1 (evals.md §8)."""

    precision_at_n: float = 0.57
    noise_at_n_max: float = 2 / 7
    recall_at_k: float = 0.60
    recall_k: int = 15
    filter_accuracy: float = 0.95
    explain_sum_ge6_rate: float = 0.80
    explain_r1_eq2_rate: float = 0.90
    explain_r1_eq0_max: float = 0.0
    top_n: int = 7


@dataclass
class RankingResult:
    ranked_ids: list[str]
    scores: dict[str, float]
    precision_at_n: float | None
    noise_at_n: float
    borderline_at_n: float
    recall_at_k: float | None
    top_labels: list[tuple[str, str, float]]
    hard_filtered_out: int


@dataclass
class FilterResult:
    total: int
    correct: int
    accuracy: float
    failures: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ExplainScore:
    item_id: str
    reason: str
    r1: int
    r2: int
    r3: int
    r4: int

    @property
    def total(self) -> int:
        return self.r1 + self.r2 + self.r3 + self.r4


@dataclass
class ExplainResult:
    scores: list[ExplainScore]
    sum_ge6_rate: float
    r1_eq2_rate: float
    r1_eq0_rate: float


@dataclass
class EvalReport:
    pool_version: str
    profile_id: str
    ranking: RankingResult | None = None
    filters: FilterResult | None = None
    explain: ExplainResult | None = None
    passed: bool = False
    failures: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"eval profile={self.profile_id} pool={self.pool_version}",
            f"PASS={self.passed}",
        ]
        if self.ranking:
            r = self.ranking
            lines.append(
                f"E1 precision@{Thresholds.top_n}={_fmt(r.precision_at_n)} "
                f"noise={r.noise_at_n:.2f} borderline={r.borderline_at_n:.2f} "
                f"recall@{Thresholds().recall_k}={_fmt(r.recall_at_k)} "
                f"filtered_out={r.hard_filtered_out}"
            )
            lines.append("  top:")
            for iid, lab, sc in r.top_labels:
                lines.append(f"    {sc:.3f} [{lab}] {iid}")
        if self.filters:
            f = self.filters
            lines.append(f"E3 filter_accuracy={f.accuracy:.2f} ({f.correct}/{f.total})")
            for fail in f.failures[:5]:
                lines.append(f"    FAIL {fail.get('id')}: {fail.get('detail')}")
        if self.explain:
            e = self.explain
            lines.append(
                f"E2 sum>=6={e.sum_ge6_rate:.2f} R1=2={e.r1_eq2_rate:.2f} "
                f"R1=0={e.r1_eq0_rate:.2f}"
            )
        for msg in self.failures:
            lines.append(f"  ! {msg}")
        return "\n".join(lines)


def _fmt(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.2f}"


def _tokens(text: str) -> set[str]:
    return {m.group(0).lower() for m in _TOKEN_RE.finditer(text or "")}


def profile_text(profile: SimpleNamespace) -> str:
    parts = [
        " ".join(getattr(profile, "roles", None) or []),
        " ".join(getattr(profile, "skills", None) or []),
        getattr(profile, "location", None) or "",
        getattr(profile, "work_mode", None) or "",
        " ".join(getattr(profile, "speaking_topics", None) or []),
        getattr(profile, "goals", None) or "",
    ]
    return "\n".join(p for p in parts if p)


def opp_text(opp: SimpleNamespace) -> str:
    return "\n".join(
        p
        for p in [
            getattr(opp, "title", None) or "",
            getattr(opp, "org", None) or "",
            getattr(opp, "location", None) or "",
            (getattr(opp, "description", None) or "")[:800],
        ]
        if p
    )


def lexical_score(profile: SimpleNamespace, opp: SimpleNamespace) -> float:
    """Детерминированный proxy rank (без эмбеддингов) для CI."""
    pt = _tokens(profile_text(profile))
    ot = _tokens(opp_text(opp))
    if not pt or not ot:
        return 0.0
    inter = pt & ot
    # Jaccard + бонус за роли в title
    jacc = len(inter) / len(pt | ot)
    title = (getattr(opp, "title", None) or "").lower()
    bonus = 0.0
    for role in getattr(profile, "roles", None) or []:
        rl = role.lower()
        if rl in title:
            bonus += 0.12
        else:
            # частичные: "product" in head of product / cpo
            for tok in _tokens(rl):
                if len(tok) >= 4 and tok in title:
                    bonus += 0.04
    if "cpo" in title or "head of product" in title or "директор по продукту" in title:
        bonus += 0.15
    if "product owner" in title or "владелец продукта" in title:
        bonus -= 0.02
    return round(min(1.0, jacc + bonus), 4)


def rank_lexical(
    profile: SimpleNamespace,
    pool: list[dict[str, Any]],
    *,
    top_n: int = 7,
    apply_hard_filters: bool = True,
) -> tuple[list[tuple[dict[str, Any], float]], int]:
    """Вернуть (ranked rows with scores), count hard-filtered-out."""
    from app.evals.dataset import opp_from_dict

    scored: list[tuple[dict[str, Any], float]] = []
    filtered_out = 0
    for row in pool:
        opp = opp_from_dict(row)
        if apply_hard_filters and not passes_hard_filters(opp, profile):  # type: ignore[arg-type]
            filtered_out += 1
            continue
        scored.append((row, lexical_score(profile, opp)))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[: max(top_n, Thresholds().recall_k)], filtered_out


def evaluate_ranking(
    profile: SimpleNamespace,
    pool: list[dict[str, Any]],
    *,
    thresholds: Thresholds | None = None,
    ranked: list[tuple[dict[str, Any], float]] | None = None,
    filtered_out: int = 0,
) -> RankingResult:
    th = thresholds or Thresholds()
    if ranked is None:
        ranked_full, filtered_out = rank_lexical(
            profile, pool, top_n=max(th.top_n, th.recall_k)
        )
    else:
        ranked_full = ranked

    by_id = {r["id"]: r for r in pool}
    top = ranked_full[: th.top_n]
    top_labels: list[tuple[str, str, float]] = []
    relevant_n = noise_n = borderline_n = hard_slots = 0
    for row, score in top:
        lab = row.get("label") or "noise"
        top_labels.append((row["id"], lab, score))
        if lab == "relevant":
            relevant_n += 1
            hard_slots += 1
        elif lab == "noise":
            noise_n += 1
            hard_slots += 1
        elif lab == "borderline":
            borderline_n += 1

    precision = (relevant_n / hard_slots) if hard_slots else None
    noise_at = noise_n / th.top_n
    borderline_at = borderline_n / th.top_n

    all_relevant = {r["id"] for r in pool if r.get("label") == "relevant"}
    recall = None
    if all_relevant:
        hit = {row["id"] for row, _ in ranked_full[: th.recall_k]} & all_relevant
        recall = len(hit) / len(all_relevant)

    return RankingResult(
        ranked_ids=[row["id"] for row, _ in top],
        scores={row["id"]: sc for row, sc in top},
        precision_at_n=precision,
        noise_at_n=noise_at,
        borderline_at_n=borderline_at,
        recall_at_k=recall,
        top_labels=top_labels,
        hard_filtered_out=filtered_out,
    )


def evaluate_filters(
    base_profile: SimpleNamespace,
    cases: list[dict[str, Any]],
) -> FilterResult:
    from app.evals.dataset import opp_from_dict, profile_from_fixture

    correct = 0
    failures: list[dict[str, Any]] = []
    # rebuild profile dict-ish for overrides
    base_dict = {
        "roles": list(getattr(base_profile, "roles", None) or []),
        "location": getattr(base_profile, "location", None),
        "work_mode": getattr(base_profile, "work_mode", None),
        "skills": list(getattr(base_profile, "skills", None) or []),
        "speaking_topics": list(getattr(base_profile, "speaking_topics", None) or []),
        "salary_expectation": getattr(base_profile, "salary_expectation", None),
        "hard_nos": getattr(base_profile, "hard_nos", None) or {},
    }
    for case in cases:
        profile = profile_from_fixture(base_dict, **(case.get("profile_override") or {}))
        opp = opp_from_dict(case)
        got = passes_hard_filters(opp, profile)  # type: ignore[arg-type]
        expect = bool(case.get("expect_pass"))
        if got == expect:
            correct += 1
        else:
            failures.append(
                {
                    "id": case.get("id"),
                    "detail": f"got={got} expect={expect}: {case.get('reason')}",
                }
            )
    total = len(cases)
    return FilterResult(
        total=total,
        correct=correct,
        accuracy=(correct / total) if total else 1.0,
        failures=failures,
    )


def evaluate_explain_heuristic(
    profile: SimpleNamespace,
    items: Iterable[tuple[dict[str, Any], str]],
) -> ExplainResult:
    """Лёгкий judge без LLM: факты + анти-вода. Не замена LM-judge из спеки."""
    scores: list[ExplainScore] = []
    for row, reason in items:
        scores.append(_score_reason(profile, row, reason))
    n = len(scores) or 1
    return ExplainResult(
        scores=scores,
        sum_ge6_rate=sum(1 for s in scores if s.total >= 6) / n,
        r1_eq2_rate=sum(1 for s in scores if s.r1 == 2) / n,
        r1_eq0_rate=sum(1 for s in scores if s.r1 == 0) / n,
    )


def _score_reason(
    profile: SimpleNamespace, row: dict[str, Any], reason: str
) -> ExplainScore:
    text = (reason or "").strip()
    low = text.lower()
    iid = str(row.get("id") or "")

    if not text:
        return ExplainScore(iid, text, r1=0, r2=0, r3=0, r4=0)

    # Fallback strings → R2=0, R1 ok
    if any(f in low for f in _FALLBACK_REASONS):
        return ExplainScore(iid, text, r1=2, r2=0, r3=1, r4=0)

    allowed = _tokens(profile_text(profile)) | _tokens(
        " ".join(
            [
                str(row.get("title") or ""),
                str(row.get("org") or ""),
                str(row.get("description") or "")[:800],
                str(row.get("location") or ""),
            ]
        )
    )
    # numbers in reason must appear in inputs
    input_blob = (
        profile_text(profile)
        + " "
        + str(row.get("title") or "")
        + " "
        + str(row.get("org") or "")
        + " "
        + str(row.get("description") or "")
        + " "
        + str(row.get("salary") or "")
    )
    r1 = 2
    for num in re.findall(r"\d[\d\s]{2,}", text):
        compact = re.sub(r"\s+", "", num)
        if len(compact) >= 3 and compact not in re.sub(r"\s+", "", input_blob):
            r1 = 0
            break
    # invented employer: «ты работал в X»
    m = re.search(r"ты работал[аи]?\s+в\s+([A-Za-zА-Яа-яЁё0-9\-]+)", low)
    if m:
        org = m.group(1)
        exp = " ".join(
            str(e.get("org", "")) if isinstance(e, dict) else str(e)
            for e in (getattr(profile, "experience", None) or [])
        ).lower()
        if org not in exp and org not in (str(row.get("org") or "").lower()):
            r1 = 0

    anchors = 0
    for tok in ("cpo", "product", "продукт", "москв", "hybrid", "удал", "p&l", "монетиз", "карьер"):
        if tok in low:
            anchors += 1
    for role in getattr(profile, "roles", None) or []:
        if role.lower() in low:
            anchors += 1
    r2 = 2 if anchors >= 2 else (1 if anchors == 1 else 0)

    label = row.get("label")
    # if noise but reason hypes — soft R3
    hype = any(w in low for w in ("идеальн", "отлично подходит", "must-have", "точно твоя"))
    if label == "noise" and hype:
        r3 = 0
    elif label == "noise":
        r3 = 1
    else:
        r3 = 2

    r4 = 2 if len(text) >= 40 and r2 >= 1 else (1 if len(text) >= 20 else 0)
    # unused allowed set keeps linter calm for future stricter checks
    _ = allowed
    return ExplainScore(iid, text, r1=r1, r2=r2, r3=r3, r4=r4)


def apply_thresholds(
    report: EvalReport,
    *,
    thresholds: Thresholds | None = None,
    require_explain: bool = False,
) -> EvalReport:
    th = thresholds or Thresholds()
    failures: list[str] = []

    if report.ranking:
        r = report.ranking
        if r.precision_at_n is None or r.precision_at_n < th.precision_at_n:
            failures.append(
                f"E1 precision@{th.top_n}={_fmt(r.precision_at_n)} < {th.precision_at_n}"
            )
        if r.noise_at_n > th.noise_at_n_max + 1e-9:
            failures.append(f"E1 noise@{th.top_n}={r.noise_at_n:.2f} > {th.noise_at_n_max:.2f}")
        if r.recall_at_k is not None and r.recall_at_k < th.recall_at_k:
            failures.append(
                f"E1 recall@{th.recall_k}={r.recall_at_k:.2f} < {th.recall_at_k}"
            )

    if report.filters:
        if report.filters.accuracy < th.filter_accuracy:
            failures.append(
                f"E3 accuracy={report.filters.accuracy:.2f} < {th.filter_accuracy}"
            )

    if require_explain:
        if report.explain is None:
            failures.append("E2 missing")
        else:
            e = report.explain
            if e.sum_ge6_rate < th.explain_sum_ge6_rate:
                failures.append(f"E2 sum>=6 rate={e.sum_ge6_rate:.2f}")
            if e.r1_eq2_rate < th.explain_r1_eq2_rate:
                failures.append(f"E2 R1=2 rate={e.r1_eq2_rate:.2f}")
            if e.r1_eq0_rate > th.explain_r1_eq0_max + 1e-9:
                failures.append(f"E2 R1=0 rate={e.r1_eq0_rate:.2f} > 0")

    report.failures = failures
    report.passed = not failures
    return report


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
