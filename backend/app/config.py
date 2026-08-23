"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    """Fathom backend configuration.

    Reads from environment variables or .env file.
    """

    DATABASE_URL: str = "postgresql+asyncpg://fathom:fathom@localhost:5432/fathom"
    FATHOM_ENDPOINT: str = "http://localhost:8000/api/v1"

    # CORS origins allowed (frontend dev server)
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # Evaluation Engine configuration (Abhishek)
    EMBEDDING_MODEL_NAME: str = "sentence-transformers/all-MiniLM-L6-v2"
    DRIFT_THRESHOLD: float = 0.70
    JUDGE_LLM_API_KEY: str | None = None
    JUDGE_LLM_MODEL: str = "gpt-4o-mini"
    OPENAI_BASE_URL: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
