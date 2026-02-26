from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Databases ─────────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://trading:trading_dev@localhost:5432/trading"
    questdb_host: str = "localhost"
    questdb_pg_port: int = 8812
    questdb_http_port: int = 9000

    # ── Security ──────────────────────────────────────────────────────────────
    # REQUIRED in production — generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    encryption_key: str = "ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg="
    jwt_secret: str = "dev-jwt-secret-change-in-production"

    # ── LLM ───────────────────────────────────────────────────────────────────
    llm_provider: str = "openai"  # openai | gemini | anthropic
    llm_confidence_threshold: float = 0.70
    openai_api_key: str = ""
    gemini_api_key: str = ""
    anthropic_api_key: str = ""

    # ── MetaTrader 5 ──────────────────────────────────────────────────────────
    mt5_path: str = ""  # leave empty to use default MT5 installation path

    # ── Application ───────────────────────────────────────────────────────────
    debug: bool = False
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:3000"]

    # ── Trading Safety ────────────────────────────────────────────────────────
    max_drawdown_percent: float = 10.0
    max_open_positions: int = 5
    default_risk_percent: float = 1.0

    @field_validator("llm_provider")
    @classmethod
    def validate_llm_provider(cls, v: str) -> str:
        allowed = {"openai", "gemini", "anthropic"}
        if v not in allowed:
            raise ValueError(f"llm_provider must be one of {allowed}")
        return v


settings = Settings()
