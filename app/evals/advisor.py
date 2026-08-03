"""Offline/structural + optional LLM-judge для advisor M9.

Пул: evals/dialogue/pools/advisor_m9_v1.jsonl
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.services import advisor_tools
from app.services.dialogue_agent import _MANAGER_PERSONA, _build_advisor_messages

ROOT = Path(__file__).resolve().parents[2]
POOL_PATH = ROOT / "evals" / "dialogue" / "pools" / "advisor_m9_v1.jsonl"

_FIXTURE_PROFILE_TEXT = (
    "Product Manager B2B\ndiscovery delivery\nМосква\nhybrid\nproduct strategy"
)

_MOCK_TOOL_CTX: dict[str, str] = {
    "get_profile": (
        "### Профиль\nТвой профиль у менеджера\n"
        "• Роли: Product Manager\n• Локация: Москва\n• Зарплата от: 500 000 RUB\n"
        "• Приоритет: работа и выступления"
    ),
    "get_job_snapshot": (
        "### Вакансии\nВ кэше сейчас нет свежих матчей по вакансиям. "
        "Честный ответ: пусто. Предложи /today или «найди вакансии»."
    ),
    "refresh_jobs": (
        "### Вакансии (live)\nЖивой поиск завершён, подходящих вакансий нет. "
        "Не выдумывай позиции. Можно позже /today."
    ),
    "get_talk_snapshot": (
        "### Выступления\nВ кэше нет конференций с датой подачи. "
        "Не предлагай масс-медиа и ТВ. Предложи «найди конференции» или /talks."
    ),
    "refresh_talks": (
        "### Выступления (live)\nЖивой поиск конференций пуст. Не предлагай НТВ и утренние шоу."
    ),
    "get_schedule": (
        "### Расписание\nДоставка: мониторинг (watch)\nТихие часы: 23:00–08:00"
    ),
}


@dataclass
class CaseResult:
    case_id: str
    tools_ok: bool
    expect_tools: list[str]
    got_tools: list[str]
    reply: str | None = None
    judge_pass: bool | None = None
    judge_notes: str = ""
    errors: list[str] = field(default_factory=list)


def load_pool(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or POOL_PATH
    rows: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def check_tools(row: dict[str, Any]) -> CaseResult:
    got = list(advisor_tools.select_tools(row["user"]))
    expect = list(row.get("expect_tools") or [])
    ok = got == expect
    errors = [] if ok else [f"tools: got {got}, expect {expect}"]
    return CaseResult(
        case_id=str(row.get("id") or "?"),
        tools_ok=ok,
        expect_tools=expect,
        got_tools=got,
        errors=errors,
    )


def _fixture_profile() -> Any:
    from types import SimpleNamespace
    from uuid import uuid4

    return SimpleNamespace(
        user_id=uuid4(),
        roles=["Product Manager"],
        skills=["B2B", "discovery"],
        location="Москва",
        work_mode="hybrid",
        speaking_topics=["product strategy"],
        goals="рост",
    )


def mock_tool_context(tools: list[str]) -> str:
    parts = [_MOCK_TOOL_CTX[t] for t in tools if t in _MOCK_TOOL_CTX]
    return "\n\n".join(parts)


async def generate_reply(row: dict[str, Any]) -> str:
    """Сгенерировать ответ советника на фикстуре (без БД)."""
    from app.llm import client as llm

    tools = list(advisor_tools.select_tools(row["user"]))
    profile = _fixture_profile()
    messages = _build_advisor_messages(
        profile=profile,  # type: ignore[arg-type]
        history=[],
        tool_context=mock_tool_context(tools),
        user_text=row["user"],
        profile_update_note="",
    )
    # Подменим краткий профиль в system на стабильный текст — уже через profile_to_text
    _ = _FIXTURE_PROFILE_TEXT
    return await llm.complete_messages(messages, tier="primary", max_tokens=600)


_JUDGE_SYSTEM = """Ты — строгий оценщик ответов карьерного менеджера в Telegram.
Верни ТОЛЬКО JSON: {"pass": true/false, "brief": "коротко латиницей"}
Правила fail:
- выдуманные вакансии/компании/CFP/дедлайны которых нет в контексте tools;
- планёр дня / to-do не про карьеру (зарядка, покупки), если пользователь просил план на день;
- пиар НТВ / утренних шоу / Первого канала как площадки;
- жаргон «CFP» в ответе пользователю;
- повторное приветствие («Здравствуйте», «Привет!»);
- противоречие фактам профиля из контекста.
pass=true если ответ честный, по делу, в зоне карьеры.
"""


async def judge_reply(row: dict[str, Any], reply: str) -> tuple[bool, str]:
    from app.llm import client as llm

    must = row.get("must") or []
    must_not = row.get("must_not") or []
    # Дешёвые эвристики до LLM
    low = reply.lower()
    for bad in must_not:
        if str(bad).lower() in low:
            return False, f"must_not hit: {bad}"
    # Явные запреты из persona-кейсов
    if row.get("id") == "a5_no_dayplan":
        if re.search(r"06:00|зарядк|список покупок|утро[:\s]", low):
            return False, "dayplan leakage"
    if re.search(r"\bздравствуйте\b|\bпривет!", low):
        return False, "greeting spam"
    if re.search(r"\bcfp\b", low):
        return False, "cfp jargon"

    prompt = (
        f"Ожидания must: {must}\nЗапреты must_not: {must_not}\n"
        f"empty_ok: {row.get('empty_ok')}\n"
        f"Реплика пользователя: {row['user']}\n"
        f"Ответ ассистента:\n{reply}"
    )
    data = await llm.complete_json(prompt, system=_JUDGE_SYSTEM, tier="cheap")
    if isinstance(data, dict):
        return bool(data.get("pass")), str(data.get("brief") or "")
    return False, "judge_parse_failed"


async def run_pool(
    *,
    with_llm: bool = False,
    with_judge: bool = False,
    path: Path | None = None,
) -> list[CaseResult]:
    rows = load_pool(path)
    results: list[CaseResult] = []
    for row in rows:
        cr = check_tools(row)
        if with_llm:
            try:
                reply = await generate_reply(row)
                cr.reply = reply
                if with_judge:
                    ok, notes = await judge_reply(row, reply)
                    cr.judge_pass = ok
                    cr.judge_notes = notes
                    if not ok:
                        cr.errors.append(f"judge: {notes}")
            except Exception as exc:  # noqa: BLE001
                cr.errors.append(f"llm: {exc}")
                cr.judge_pass = False
        results.append(cr)
    return results
