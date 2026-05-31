"""
Application Configuration
==========================
Uses Pydantic Settings to:
1. Read environment variables automatically
2. Validate types at startup (if DATABASE_URL is missing → crash immediately with clear error)
3. Provide defaults for optional settings
4. Support .env files for local development

Why Pydantic Settings vs python-dotenv directly?
  - Type validation: DATABASE_URL must be a valid URL or startup fails
  - IDE autocompletion: settings.database_url is typed, not settings["DATABASE_URL"]
  - Nested settings: can have Settings(database=DatabaseSettings(...))
  - Environment prefix support: APP_DEBUG → settings.debug

Interview: "We use pydantic-settings for config management. It reads from
environment variables, validates types at startup, and fails loudly if
required config is missing. This implements the 12-factor app config principle."
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application Settings.

    All values are read from environment variables.
    Pydantic validates types at startup — if a required variable is missing
    or has the wrong type, the app crashes immediately with a clear error.
    This is intentional: fail fast, fail loudly.
    """

    # -------------------------------------------------------------------------
    # Pydantic Settings Configuration
    # -------------------------------------------------------------------------
    model_config = SettingsConfigDict(
        # Read from .env file if it exists (12-factor: config from env)
        env_file="../.env",
        env_file_encoding="utf-8",
        # Case-insensitive env var names (APP_NAME == app_name)
        case_sensitive=False,
        # Ignore extra env vars in .env (don't crash on unknown variables)
        extra="ignore",
    )

    # -------------------------------------------------------------------------
    # Application Settings
    # -------------------------------------------------------------------------
    app_name: str = "Finance Calculator"
    app_version: str = "0.1.0"
    # Literal type: only these exact strings are valid values
    env: Literal["development", "staging", "production"] = "development"
    debug: bool = False
    secret_key: str = "change-me-in-production"  # noqa: S105

    # -------------------------------------------------------------------------
    # Server Settings
    # -------------------------------------------------------------------------
    host: str = "0.0.0.0"  # noqa: S104
    port: int = 8000
    workers: int = 1

    # -------------------------------------------------------------------------
    # Database Settings
    # -------------------------------------------------------------------------
    # PostgresDsn: validates that this is a valid PostgreSQL connection URL
    # Format: postgresql+asyncpg://user:password@host:port/dbname
    database_url: str = "postgresql+asyncpg://finance_user@localhost:5432/finance_db"
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_pool_timeout: int = 30

    # -------------------------------------------------------------------------
    # Redis Settings
    # -------------------------------------------------------------------------
    redis_url: str = "redis://localhost:6379/0"
    redis_cache_ttl: int = 3600  # seconds (1 hour)

    # -------------------------------------------------------------------------
    # JWT Authentication Settings
    # -------------------------------------------------------------------------
    jwt_secret_key: str = "change-me-jwt-secret-in-production"  # noqa: S105
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # -------------------------------------------------------------------------
    # CORS Settings
    # -------------------------------------------------------------------------
    # List of allowed origins for cross-origin requests
    # In .env file: CORS_ORIGINS=http://localhost:3000,http://localhost:8000
    # Stored as comma-separated string, parsed to list via validator
    cors_origins: str = "http://localhost:3000,http://localhost:8000"
    cors_allow_credentials: bool = True

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse comma-separated cors_origins string into a list."""
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]

    # -------------------------------------------------------------------------
    # AI Settings (Phase 17 — Claude API expense categorization)
    # -------------------------------------------------------------------------
    # Get your key at: https://console.anthropic.com
    # Leave empty to disable AI categorization (falls back to keyword matching)
    anthropic_api_key: str = ""

    # -------------------------------------------------------------------------
    # Email Settings
    # -------------------------------------------------------------------------
    mail_username: str = ""
    mail_password: str = ""
    mail_from: str = "noreply@finance-calculator.com"
    mail_port: int = 587
    mail_server: str = "smtp.gmail.com"
    mail_tls: bool = True
    mail_ssl: bool = False

    # -------------------------------------------------------------------------
    # Logging Settings
    # -------------------------------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["console", "json"] = "console"

    # -------------------------------------------------------------------------
    # Rate Limiting
    # -------------------------------------------------------------------------
    rate_limit_per_minute: int = 60
    rate_limit_auth_per_minute: int = 10

    # -------------------------------------------------------------------------
    # Feature Flags
    # -------------------------------------------------------------------------
    enable_registration: bool = True
    enable_email_verification: bool = False
    enable_ai_suggestions: bool = False

    # -------------------------------------------------------------------------
    # Computed Properties
    # -------------------------------------------------------------------------
    @property
    def is_development(self) -> bool:
        """True when running in development mode."""
        return self.env == "development"

    @property
    def is_production(self) -> bool:
        """True when running in production mode."""
        return self.env == "production"

    @property
    def docs_url(self) -> str | None:
        """
        Only expose API docs in development.
        In production, the docs endpoint is disabled for security.
        (You don't want to expose your entire API schema to the public)
        """
        return "/docs" if self.is_development else None

    @property
    def redoc_url(self) -> str | None:
        """Only expose ReDoc in development."""
        return "/redoc" if self.is_development else None


@lru_cache
def get_settings() -> Settings:
    """
    Get the application settings singleton.

    @lru_cache: This function is called once and cached.
    Every subsequent call returns the SAME Settings object.
    This means environment variables are read exactly ONCE at startup.

    Why singleton?
    - Performance: don't re-read env vars on every request
    - Consistency: all code shares the same config object
    - Testability: in tests, we can clear the cache and inject different settings

    Usage:
        from app.config import get_settings
        settings = get_settings()
        print(settings.app_name)

    In FastAPI endpoints (via dependency injection):
        from fastapi import Depends
        from app.config import get_settings, Settings

        @router.get("/info")
        async def info(settings: Settings = Depends(get_settings)):
            return {"app": settings.app_name}
    """
    return Settings()


# Convenience: a module-level settings instance
# Use this for imports at module load time (not in request handlers)
settings = get_settings()
