"""FastAPI-приложение: health-check и (позже) API для Mini App.

Спека: docs/architecture/overview.md
"""

from fastapi import FastAPI

app = FastAPI(title="Kabi")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
