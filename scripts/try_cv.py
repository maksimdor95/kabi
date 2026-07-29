"""Dev-утилита: прогнать парсинг CV и напечатать извлечённый профиль.

Запуск: python scripts/try_cv.py <path-to-cv>
"""

import asyncio
import sys
from dataclasses import asdict

from app.services import cv_parser


async def main(path: str) -> None:
    draft = await cv_parser.parse_cv(path)
    import json

    print(json.dumps(asdict(draft), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
