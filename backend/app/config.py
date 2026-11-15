from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_env: str = "dev"
    app_name: str = "FINN"
    cors_origins: str = "http://localhost:3000"

    database_url: str = "sqlite:///./data/finn.db"

    llm_cheap_provider: str = "anthropic"
    llm_cheap_model: str = "claude-haiku-5-5"
    llm_strong_provider: str = "anthropic"
    llm_strong_model: str = "claude-opus-5-5"
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    groq_api_key: str = ""
    llm_cache_enabled: bool = True

    http_user_agent: str = "Mozilla/5.0"
    screener_base_url: str = "https://www.screener.in"
    nse_base_url: str = "https://www.nseindia.com"
    docs_cache_dir: str = "./data/docs"

    default_digest_window_hours: int = 24
    default_volume_spike_multiple: float = 2.0
    default_volume_lookback_days: int = 20
    default_price_move_pct: float = 5.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def resolved_database_url(self) -> str:
        """Make relative SQLite paths relative to backend/, not the CWD."""
        prefix = "sqlite:///./"
        if self.database_url.startswith(prefix):
            path = BACKEND_DIR / self.database_url[len(prefix):]
            path.parent.mkdir(parents=True, exist_ok=True)
            return f"sqlite:///{path.as_posix()}"
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
