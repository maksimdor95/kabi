# Matching evals (M8) + advisor (M9)

Методология matching: [`docs/services/evals.md`](../docs/services/evals.md).  
Advisor: [`docs/services/dialogue-agent.md`](../docs/services/dialogue-agent.md) §8.

## Advisor (M9)

| Путь | Содержание |
|------|------------|
| `dialogue/pools/advisor_m9_v1.jsonl` | Реплики + expect_tools + must/must_not |

```bash
# Только контракт роутера (без API)
PYTHONPATH=. python scripts/run_advisor_eval.py

# Ответы модели + LM-judge
PYTHONPATH=. python scripts/run_advisor_eval.py --llm --judge
```

## Matching (M8) — данные

| Путь | Содержание |
|------|------------|
| `matching/profiles/marina_v1.json` | Эталонный профиль |
| `matching/pools/jobs_hh_sj_v1.jsonl` | ~70 вакансий HH (фаза 1) |
| `matching/pools/jobs_m7_v2.jsonl` | HH + Habr/Getmatch/TG после M7 |
| `matching/gold/filter_negatives_v1.jsonl` | E3 hard filters |
| `matching/gold/explain_human_v1.jsonl` | Human gold для калибровки LM-judge |
| `matching/cache/marina_v1__jobs_hh_sj_v1.json` | Кэш query/doc эмбеддингов |
| `matching/rubrics/explain_v1.md` | Rubric E2 |
| `reports/` | JSON-отчёты (gitignore) |

## Matching — запуск

```bash
PYTHONPATH=. python scripts/run_matching_eval.py --mode embed
PYTHONPATH=. python scripts/build_eval_embedding_cache.py
PYTHONPATH=. python scripts/run_matching_eval.py --calibrate-judge
PYTHONPATH=. python scripts/run_matching_eval.py --mode embed --judge
PYTHONPATH=. python scripts/run_matching_eval.py --mode lexical
PYTHONPATH=. python scripts/run_matching_eval.py --mode lexical --pool jobs_m7_v2
```

## Тесты

```bash
pytest tests/test_matching_evals.py tests/test_advisor_m9.py tests/test_advisor_profile.py -q
```
