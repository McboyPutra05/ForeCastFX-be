"""
app/core/config.py
Pydantic Settings — loads configuration from environment variables / .env file.
Single source of truth for all backend configuration values.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ────────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@db:5432/info_trader"
    DATABASE_URL_SYNC: str = "postgresql://postgres:password@db:5432/info_trader"

    # ── JWT Authentication ──────────────────────────────────────────────────
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_MINUTES: int = 1440  # 24 hours

    # ── Alpha Vantage API ────────────────────────────────────────────────────
    ALPHA_VANTAGE_API_KEY: str = ""

    # ── Redis (Celery Broker) ───────────────────────────────────────────────
    REDIS_URL: str = "redis://redis:6379/0"

    # ── CORS ────────────────────────────────────────────────────────────────
    CORS_ORIGINS: str = "http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse comma-separated CORS origins into a list."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]


# Singleton settings instance
settings = Settings()
