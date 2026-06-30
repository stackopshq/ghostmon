from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["development", "staging", "production"] = "development"
    app_debug: bool = False
    app_secret_key: str = Field(min_length=16)

    database_url: str = "postgresql+asyncpg://ghostmon:ghostmon@localhost:5432/ghostmon"
    database_echo: bool = False

    jwt_algorithm: str = "HS256"
    jwt_access_ttl_minutes: int = 60

    oidc_enabled: bool = False
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_redirect_uri: str | None = None

    argon2_time_cost: int = 3
    argon2_memory_cost: int = 65536
    argon2_parallelism: int = 4

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "ghostmonitor@localhost"
    smtp_starttls: bool = True

    public_base_url: str = "http://localhost:8000"

    # Metric history retention. Samples (and probe results) older than this are
    # pruned hourly. 0 disables pruning (keep everything).
    history_retention_days: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
