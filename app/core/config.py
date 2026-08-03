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

    # ---------------------------------------------------------------------------------
    # Google Maps / Google Places lead collection
    # ---------------------------------------------------------------------------------
    # Credentials for the `google_maps` lead provider. The API key has no default on
    # purpose: an empty key makes the provider report itself unavailable and refuse to run
    # with a clear message, which is far better than a hardcoded placeholder that fails at
    # request time with an opaque 403 from Google.
    GOOGLE_MAPS_API_KEY: str = ""

    #: Base URL of the Places API. Configurable so a test or a proxy can point the provider
    #: at a stub server without patching the adapter.
    GOOGLE_MAPS_BASE_URL: str = "https://maps.googleapis.com/maps/api/place"

    #: Per-request timeout, in seconds, for a single call to Google.
    GOOGLE_MAPS_TIMEOUT_SECONDS: float = 15.0

    #: Region bias for Text Search (ccTLD form). The CRM's market is India, and biasing the
    #: search keeps "Photographer Kozhikode" from matching similarly-named places abroad.
    GOOGLE_MAPS_REGION: str = "in"

    #: Language for returned place names and addresses.
    GOOGLE_MAPS_LANGUAGE: str = "en"

    #: Whether to spend a Place Details call per result. Details is the only source of
    #: phone, website and opening hours, so this defaults on — but it is billed per call,
    #: so an operator running a wide survey can switch it off and accept name/address only.
    GOOGLE_MAPS_FETCH_DETAILS: bool = True

    #: Maximum Text Search result pages to walk. Google returns 20 results per page and
    #: caps pagination at 3 pages (60 results) regardless of what is asked for.
    GOOGLE_MAPS_MAX_PAGES: int = 3

    # ---------------------------------------------------------------------------------
    # Instagram lead collection (Instagram Graph API — Business Discovery)
    # ---------------------------------------------------------------------------------
    # Credentials for the `instagram` lead provider. Business Discovery is the only
    # sanctioned way to read another business's public profile, and it needs BOTH a
    # long-lived access token AND the caller's own IG Business account id — the API is
    # shaped as "my account asks about that username", not as an anonymous lookup. Neither
    # has a default: an unset credential makes the provider report itself unavailable and
    # refuse with a clear message, rather than failing mid-run with an opaque 190 from Meta.
    INSTAGRAM_ACCESS_TOKEN: str = ""

    #: The IG Business/Creator account id that Business Discovery queries are issued *as*.
    INSTAGRAM_BUSINESS_ACCOUNT_ID: str = ""

    #: Base URL of the Graph API. Configurable so a test or proxy can point the provider at
    #: a stub server without patching the adapter.
    INSTAGRAM_GRAPH_BASE_URL: str = "https://graph.facebook.com"

    #: Graph API version. Meta versions its API and retires versions on a schedule, so this
    #: is configurable to allow an upgrade without a code change.
    INSTAGRAM_GRAPH_API_VERSION: str = "v21.0"

    #: Per-request timeout, in seconds, for a single call to the Graph API.
    INSTAGRAM_TIMEOUT_SECONDS: float = 15.0

    #: Number of Business Discovery lookups in flight at once. Bounded so a wide run does
    #: not open dozens of concurrent sockets to Meta and trip its per-app rate limit.
    INSTAGRAM_CONCURRENCY: int = 5

    #: How many hashtag result pages to walk while discovering candidate usernames. Each
    #: page is a billed/rate-limited call, so this bounds the discovery half of a run.
    INSTAGRAM_MAX_PAGES: int = 3

    #: Whether to drop profiles that expose no phone number. Business Discovery returns a
    #: phone only for accounts that publish one; a lead without a phone is rejected by
    #: `NormalizedLead.is_valid()` anyway, so this defaults on to keep the failed-record
    #: count meaningful. Switch it off to survey what exists and accept mass failures.
    INSTAGRAM_REQUIRE_CONTACT: bool = True

    #: Minimum follower count for a discovered profile to be worth importing. Filters out
    #: dormant and hobbyist accounts before they consume a lookup. 0 disables the filter.
    INSTAGRAM_MIN_FOLLOWERS: int = 0

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
