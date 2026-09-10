from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Every value comes from the environment (or a
    local .env file); this is the only module that reads it."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    # How long startup will keep retrying the database before giving up.
    db_startup_timeout_seconds: float = 30.0

    @field_validator("database_url")
    @classmethod
    def _use_psycopg2_driver(cls, value: str) -> str:
        # Hosted Postgres (Neon, Heroku-style) hands out postgres:// URLs;
        # SQLAlchemy needs the dialect+driver form.
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+psycopg2://" + value[len(prefix):]
        return value

    # Auth. The secret signs every access token; rotating it logs everyone out.
    # 32 bytes is the HMAC-SHA256 floor (RFC 7518); refuse to start with less.
    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    # Long by default because the widget holds one token and has no refresh flow.
    access_token_expire_minutes: int = 43_200  # 30 days

    # LLM categorization. Any OpenAI-compatible chat endpoint works; Google's
    # Gemini free tier is the default. Leaving the key unset disables
    # /categorize only.
    llm_api_key: str | None = None
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    llm_model: str = "gemini-3.5-flash"
    llm_timeout_seconds: float = 25.0


settings = Settings()
