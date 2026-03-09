import json

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_ENCRYPTION_KEY = "ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg="
_DEV_JWT_SECRET = "dev-jwt-secret-change-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    # ── Databases ─────────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://trading:trading_dev@localhost:5432/trading"
    questdb_host: str = "localhost"
    questdb_pg_port: int = 8812
    questdb_http_port: int = 9000
    questdb_user: str = "admin"
    questdb_password: str = "quest"
    questdb_db: str = "qdb"
    redis_url: str = "redis://localhost:6379/0"

    # ── Security ──────────────────────────────────────────────────────────────
    # REQUIRED in production — generate with:
    # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    encryption_key: str = _DEV_ENCRYPTION_KEY
    jwt_secret: str = _DEV_JWT_SECRET

    # ── LLM ───────────────────────────────────────────────────────────────────
    llm_provider: str = "openai"  # openai | gemini | anthropic
    llm_confidence_threshold: float = 0.70
    openai_api_key: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"  # override with GEMINI_MODEL in .env
    anthropic_api_key: str = ""

    # ── MetaTrader 5 ──────────────────────────────────────────────────────────
    mt5_path: str = ""  # leave empty to use default MT5 installation path

    # ── Application ───────────────────────────────────────────────────────────
    debug: bool = False
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:3000"]
    news_enabled: bool = False  # Set NEWS_ENABLED=true in .env to enable ForexFactory calendar

    # ── Alerting ──────────────────────────────────────────────────────────────
    telegram_bot_token: str = ""    # BotFather token — leave empty to disable
    telegram_chat_id: str = ""      # Target chat/channel ID

    # ── Trading Safety ────────────────────────────────────────────────────────
    max_drawdown_percent: float = 10.0
    max_open_positions: int = 5
    default_risk_percent: float = 1.0

    # ── Maintenance Task ───────────────────────────────────────────────────────
    maintenance_interval_minutes: int = 60  # set MAINTENANCE_INTERVAL_MINUTES in .env
    maintenance_task_enabled: bool = True   # set MAINTENANCE_TASK_ENABLED=false to disable globally

    # ── Field validators ──────────────────────────────────────────────────────

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: object) -> object:
        if not isinstance(v, str):
            return v
        v = v.strip()
        if not v:
            return ["http://localhost:3000"]
        # Accept JSON array: '["http://localhost:3000"]'
        if v.startswith("["):
            return json.loads(v)
        # Accept comma-separated: "http://localhost:3000,http://localhost:8000"
        return [origin.strip() for origin in v.split(",") if origin.strip()]

    @field_validator("llm_provider")
    @classmethod
    def validate_llm_provider(cls, v: str) -> str:
        allowed = {"openai", "gemini", "anthropic"}
        if v not in allowed:
            raise ValueError(f"llm_provider must be one of {allowed}, got '{v}'")
        return v

    @field_validator("llm_confidence_threshold")
    @classmethod
    def validate_confidence_threshold(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(
                f"llm_confidence_threshold must be between 0.0 and 1.0, got {v}"
            )
        return v

    @field_validator("max_drawdown_percent")
    @classmethod
    def validate_max_drawdown(cls, v: float) -> float:
        if not 0.0 < v <= 100.0:
            raise ValueError(
                f"max_drawdown_percent must be between 0 and 100 (exclusive), got {v}"
            )
        return v

    @field_validator("default_risk_percent")
    @classmethod
    def validate_default_risk(cls, v: float) -> float:
        if not 0.0 < v <= 100.0:
            raise ValueError(
                f"default_risk_percent must be between 0 and 100 (exclusive), got {v}"
            )
        return v

    @field_validator("maintenance_interval_minutes")
    @classmethod
    def validate_maintenance_interval(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"maintenance_interval_minutes must be >= 1, got {v}")
        return v

    @field_validator("max_open_positions")
    @classmethod
    def validate_max_open_positions(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"max_open_positions must be at least 1, got {v}")
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {allowed}, got '{v}'")
        return upper

    # ── Cross-field / post-init validation ────────────────────────────────────

    @model_validator(mode="after")
    def validate_secrets_and_api_keys(self) -> "Settings":
        # In production (debug=False) refuse to start with dev-default secrets
        if not self.debug:
            if self.encryption_key == _DEV_ENCRYPTION_KEY:
                raise ValueError(
                    "ENCRYPTION_KEY is set to the insecure dev default. "
                    "Generate a new key: "
                    'python -c "from cryptography.fernet import Fernet; '
                    'print(Fernet.generate_key().decode())"'
                )
            if self.jwt_secret == _DEV_JWT_SECRET:
                raise ValueError(
                    "JWT_SECRET is set to the insecure dev default. "
                    "Set a strong random secret in .env."
                )

        # The API key for the active provider must be present (all modes)
        _provider_key_map: dict[str, tuple[str, str]] = {
            "openai": ("openai_api_key", "OPENAI_API_KEY"),
            "gemini": ("gemini_api_key", "GEMINI_API_KEY"),
            "anthropic": ("anthropic_api_key", "ANTHROPIC_API_KEY"),
        }
        attr, env_var = _provider_key_map[self.llm_provider]
        if not getattr(self, attr):
            raise ValueError(
                f"llm_provider is '{self.llm_provider}' but {env_var} is not set. "
                f"Add {env_var}=<your-key> to backend/.env"
            )

        return self


settings = Settings()
