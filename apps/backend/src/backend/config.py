from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    database_url: str = "postgresql+asyncpg://atlas_app:atlas_app@localhost:5432/atlas"
    migration_database_url: str = (
        "postgresql+psycopg://atlas_owner:atlas_owner@localhost:5432/atlas"
    )
    pipeline_database_url: str = "postgresql://atlas_pipeline:atlas_pipeline@localhost:5432/atlas"
    bootstrap_database_url: str = "postgresql://atlas:atlas@localhost:5432/postgres"

    session_secret: str = "dev-only-insecure-session-secret-change-me"
    session_ttl_minutes: int = 60
    cookie_secure: bool = False

    frontend_url: str = "http://127.0.0.1:3100"
    cors_extra_origin_regex: str | None = None
    api_url: str = "http://127.0.0.1:8000"
    demo_mode: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
