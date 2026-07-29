"""Конфигурация из переменных окружения (.env). См. .env.example"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str = ""

    # Yandex Cloud Foundation Models (OpenAI-совместимый API)
    llm_api_key: str = ""
    llm_base_url: str = "https://llm.api.cloud.yandex.net/v1"
    llm_folder_id: str = ""
    llm_model_primary: str = ""
    llm_model_cheap: str = ""
    llm_model_embed_doc: str = ""
    llm_model_embed_query: str = ""

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "kabi"
    postgres_user: str = "kabi"
    postgres_password: str = "change-me"

    redis_url: str = "redis://localhost:6379/0"

    # --- Ingestion: job boards (переиспользовано из Leo AI) ---
    hh_api_url: str = "https://api.hh.ru"
    hh_api_key: str = ""  # APPL-токен приложения dev.hh.ru (поиск вакансий)
    hh_user_agent: str = "KabiCareerManager/0.1 (personal)"
    superjob_api_url: str = "https://api.superjob.ru/2.0"
    superjob_api_key: str = ""  # X-Api-App-Id (v3....)
    superjob_town: int = 4  # Москва в справочнике SuperJob
    ingestion_keyword_limit: int = 5
    ingestion_per_keyword: int = 30

    # LinkedIn enrichment bypass (осознанное нарушение ToS; personal MVP)
    # li_at — cookie сессии из браузера (Application → Cookies → linkedin.com → li_at)
    linkedin_li_at: str = ""
    linkedin_jsessionid: str = ""

    app_env: str = "local"
    log_level: str = "INFO"


settings = Settings()
