# Matching evals (M8)

Методология: [`docs/services/evals.md`](../docs/services/evals.md).

## Данные

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

## Запуск

```bash
# E1 embed (кэш) + E3 — default, если кэш есть
PYTHONPATH=. python scripts/run_matching_eval.py --mode embed

# Пересобрать кэш (нужен Yandex API)
PYTHONPATH=. python scripts/build_eval_embedding_cache.py

# Калибровка LM-judge vs human (R1 ≥ 0.7)
PYTHONPATH=. python scripts/run_matching_eval.py --calibrate-judge

# Полный gate E1+E2+E3
PYTHONPATH=. python scripts/run_matching_eval.py --mode embed --judge

# CI / локально без API
PYTHONPATH=. python scripts/run_matching_eval.py --mode lexical
PYTHONPATH=. python scripts/run_matching_eval.py --mode lexical --pool jobs_m7_v2
```

## Тесты

```bash
pytest tests/test_matching_evals.py -q
```
