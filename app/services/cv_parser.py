"""Парсинг CV: извлечение текста (PDF/DOCX) + структурирование через LLM.

Спека: docs/services/profile.md  (этап M1)
Guardrail: не выдумывать факты — извлекаем только то, что есть в тексте CV.
"""

from __future__ import annotations

from pathlib import Path

from app.domain.profile import ProfileDraft
from app.llm import client as llm
from app.observability.logging import get_logger

logger = get_logger("kabi.cv")

_EXTRACTION_SYSTEM = (
    "Ты — ассистент, извлекающий структуру карьерного профиля из текста резюме. "
    "Возвращай ТОЛЬКО факты, явно присутствующие в тексте. Не выдумывай навыки, роли "
    "или опыт. Отвечай строго валидным JSON без пояснений."
)

_EXTRACTION_PROMPT = """Извлеки из текста резюме JSON со следующими полями:
- roles: массив желаемых/целевых должностей (строки)
- skills: массив ключевых навыков (строки)
- location: город проживания (строка или null)
- languages: массив языков с уровнем (строки)
- work_mode: один из "remote" | "hybrid" | "office" | null (по предпочтениям формата работы)
- experience: массив объектов {{"company": str, "role": str, "period": str}}
- speaking_topics: массив тем, на которые кандидат мог бы выступать (выведи из опыта; [] если неясно)
- goals: краткая карьерная цель (строка или null)
- salary_expectation: ожидания по зарплате из текста резюме или null.
  Если указана желаемая/ожидаемая ЗП — объект {{"min": число (целое, без пробелов), "currency": "RUB"|"USD"|"EUR"}}.
  Если вилка «от X до Y» — min = нижняя граница. Если суммы нет в тексте — null.

Текст резюме:
\"\"\"
{cv_text}
\"\"\"
"""


def extract_text(file_path: str) -> str:
    """Извлечь сырой текст из CV-файла (PDF/DOCX/TXT)."""
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages).strip()

    if suffix == ".docx":
        import docx

        document = docx.Document(str(path))
        return "\n".join(p.text for p in document.paragraphs).strip()

    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8").strip()

    raise ValueError(f"Неподдерживаемый формат CV: {suffix} (нужен PDF/DOCX/TXT)")


def _draft_from_dict(data: dict) -> ProfileDraft:
    salary = _normalize_salary(data.get("salary_expectation"))
    return ProfileDraft(
        roles=list(data.get("roles") or []),
        skills=list(data.get("skills") or []),
        location=data.get("location"),
        languages=list(data.get("languages") or []),
        work_mode=data.get("work_mode"),
        experience=list(data.get("experience") or []),
        speaking_topics=list(data.get("speaking_topics") or []),
        goals=data.get("goals"),
        salary_expectation=salary,
    )


def _normalize_salary(raw) -> dict | None:
    """Привести salary_expectation из LLM к {{min, currency}} или None."""
    if not isinstance(raw, dict):
        return None
    try:
        minimum = int(raw.get("min") or 0)
    except (TypeError, ValueError):
        return None
    if minimum <= 0:
        return None
    currency = str(raw.get("currency") or "RUB").upper()
    if currency not in {"RUB", "USD", "EUR"}:
        currency = "RUB"
    return {"min": minimum, "currency": currency}


async def extract_profile_fields(cv_text: str) -> ProfileDraft:
    """Структурировать текст CV в ProfileDraft через LLM."""
    if not cv_text.strip():
        raise ValueError("Пустой текст CV")
    data = await llm.complete_json(
        _EXTRACTION_PROMPT.format(cv_text=cv_text[:20000]),
        system=_EXTRACTION_SYSTEM,
        tier="primary",
    )
    if not isinstance(data, dict):
        raise ValueError(f"LLM вернул не объект: {type(data)}")
    return _draft_from_dict(data)


async def parse_cv(file_path: str) -> ProfileDraft:
    """Полный парсинг CV-файла в черновик профиля."""
    text = extract_text(file_path)
    logger.info("cv_extracted chars=%d file=%s", len(text), Path(file_path).name)
    return await extract_profile_fields(text)
