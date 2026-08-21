from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

PROVIDERS_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "providers.yaml"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str
    celery_broker_url: str = "redis://localhost:6379/0"

    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    groq_api_key: str | None = None
    openrouter_api_key: str | None = None
    together_api_key: str | None = None
    fireworks_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434/v1"
    embedding_provider_api_key: str | None = None
    ocr_fallback_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_provider_config() -> dict[str, Any]:
    with PROVIDERS_CONFIG_PATH.open() as f:
        return yaml.safe_load(f)
