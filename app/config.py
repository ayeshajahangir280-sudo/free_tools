from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration from environment variables (or a local .env file)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    # Comma-separated list of allowed browser origins, e.g. "https://freetoolshub.com,https://www.freetoolshub.com"
    cors_origins: str = "http://localhost:3000"
    # Maximum request body in bytes (contact messages are small)
    max_body_bytes: int = 16_384
    # Simple per-IP rate limit for the contact endpoint
    contact_rate_limit: int = 5
    contact_rate_window_seconds: int = 3600
    # Where contact messages are appended (JSON lines). Use a persistent volume in production.
    contact_store_path: str = "data/messages.jsonl"
    # Optional SMTP forwarding (any provider; free tiers exist). Leave smtp_host empty to disable.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    contact_to_email: str = ""
    # Trust X-Forwarded-For from a reverse proxy (only enable behind a trusted proxy)
    trust_proxy: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
