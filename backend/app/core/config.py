"""RetailCopy AI — Application Configuration."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_env: Literal["development", "staging", "production"] = "development"
    app_name: str = "RetailCopy AI"
    app_version: str = "1.0.0"
    secret_key: str = "change-me-in-production"
    log_level: str = "INFO"

    # Database
    database_url: str = f"sqlite:///{BASE_DIR}/data/retailcopy.db"

    # CORS
    frontend_origin: str = "http://localhost:5173"

    # Active AI Provider
    llm_provider: Literal["gemini", "groq", "openrouter", "openai_compatible", "ollama", "demo"] = "demo"

    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-flash"

    # Groq
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # OpenRouter
    openrouter_api_key: str = ""
    openrouter_model: str = "mistralai/mistral-7b-instruct"

    # OpenAI-compatible
    openai_compatible_base_url: str = "http://localhost:11434/v1"
    openai_compatible_api_key: str = ""
    openai_compatible_model: str = "gpt-3.5-turbo"

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gemma2"

    # Data Sources
    dummyjson_base_url: str = "https://dummyjson.com"
    open_food_facts_base_url: str = "https://world.openfoodfacts.org"

    # Import limits
    import_page_size: int = Field(default=30, ge=1, le=100)
    import_max_records: int = Field(default=500, ge=1)
    import_file_max_mb: int = Field(default=10, ge=1)

    # Batch processing
    batch_size: int = Field(default=10, ge=1)
    batch_concurrency: int = Field(default=3, ge=1, le=10)
    batch_retry_limit: int = Field(default=3, ge=0)
    batch_retry_backoff_base: float = Field(default=2.0, ge=1.0)

    # HTTP client
    http_timeout_seconds: int = Field(default=30, ge=5)
    http_max_retries: int = Field(default=3, ge=0)

    @field_validator("database_url", mode="before")
    @classmethod
    def ensure_data_dir(cls, v: str) -> str:
        if v.startswith("sqlite:///"):
            db_path = Path(v.replace("sqlite:///", ""))
            if not db_path.is_absolute():
                db_path = BASE_DIR / db_path
            db_path.parent.mkdir(parents=True, exist_ok=True)
        return v

    @property
    def is_demo_mode(self) -> bool:
        return self.llm_provider == "demo" or not self._has_active_key()

    def _has_active_key(self) -> bool:
        provider = self.llm_provider
        keys = {
            "gemini": self.gemini_api_key,
            "groq": self.groq_api_key,
            "openrouter": self.openrouter_api_key,
            "openai_compatible": self.openai_compatible_api_key,
            "ollama": "ollama-no-key-needed",
            "demo": "",
        }
        return bool(keys.get(provider, ""))


@lru_cache
def get_settings() -> Settings:
    return Settings()
