"""
app/core/config.py

This file defines the application's configuration settings using Pydantic Settings (Pydantic v2).
Pydantic Settings reads variables from environment variables or a `.env` file, validates their
types, and stores them in a single, type-safe configuration object. This decouples environment
configuration from application logic, preventing starting the app with invalid or missing settings.
"""

from typing import Any, List, Union
import json
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Settings class that loads configurations from .env or environment variables.
    Provides automatic validation and computes database URIs dynamically.
    """
    model_config = SettingsConfigDict(
        # Load env vars from .env file
        env_file=".env",
        # Ignore empty values in .env, letting actual environment variables override them
        env_ignore_empty=True,
        # Ignore extra parameters passed to settings
        extra="ignore"
    )

    # Project Information
    PROJECT_NAME: str = "Colour Labs CRM"
    ENV: str = "development"  # e.g., development, staging, production
    API_V1_STR: str = "/api/v1"

    # Security & Authentication Settings
    SECRET_KEY: str = "supersecret_default_key_for_colourlabs_erp_jwt_signing"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    MAX_LOGIN_ATTEMPTS: int = 5
    LOCKOUT_DURATION_MINUTES: int = 15


    # CORS Settings
    # Supports JSON lists e.g. ["http://localhost:3000"] or comma-separated values
    BACKEND_CORS_ORIGINS: Union[List[str], str] = []

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Any) -> Union[List[str], str]:
        """
        Parses the CORS origins if configured as a JSON array or a comma-separated string.
        """
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            if isinstance(v, str):
                try:
                    return json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    pass
            return v
        return []

    # PostgreSQL Database Credentials
    POSTGRES_SERVER: str
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str

    @property
    def ASYNC_DATABASE_URI(self) -> str:
        """
        Generates the asynchronous database connection URI (uses asyncpg driver).
        Example: postgresql+asyncpg://postgres:postgres@localhost:5432/colourlabs_crm
        """
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    @property
    def SYNC_DATABASE_URI(self) -> str:
        """
        Generates the synchronous database connection URI (uses default postgresql driver).
        Required for Alembic migrations, which are traditionally run synchronously.
        Example: postgresql://postgres:postgres@localhost:5432/colourlabs_crm
        """
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"


# Instantiate a singleton config object to be imported across the application
settings = Settings()
