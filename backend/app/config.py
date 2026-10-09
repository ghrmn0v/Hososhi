from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "hososhi-api"
    app_version: str = "0.1.0"
    environment: str = "development"
    log_level: str = "INFO"

    database_url: str = "sqlite:///./hososhi.db"

    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    ai_provider: str = "gemini"
    ai_model: str = ""
    ai_api_key: str = ""
    ai_timeout_seconds: int = 20
    ai_max_retries: int = 2

    # Requests at or above this amount require explicit manager approval. The
    # workflow already has a HUMAN REQUIRED approval step, so this threshold is
    # what makes that step mandatory rather than optional.
    human_approval_amount_threshold: float = 5000.0
    # Requests at or above this amount escalate even HUMAN REVIEW steps to a hard
    # human gate. This is the override the backend enforces over any AI class.
    high_value_review_threshold: float = 25000.0
    currency: str = "USD"

    dataset_seed: int = 20261009
    dataset_name: str = "hososhi-synthetic-procurement-v1"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()