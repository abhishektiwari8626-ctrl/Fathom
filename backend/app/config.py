"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Fathom backend configuration.

    Reads from environment variables or .env file.
    """

    DATABASE_URL: str = "postgresql+asyncpg://fathom:fathom@localhost:5432/fathom"
    FATHOM_ENDPOINT: str = "http://localhost:8000/api/v1"

    # CORS origins allowed (frontend dev server)
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
