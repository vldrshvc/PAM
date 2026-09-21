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

    # Digital Asset Links for the Android app. Chrome hides its UI in the
    # Trusted Web Activity only if /.well-known/assetlinks.json names the
    # app's package and signing certificate. Empty fingerprints = no file.
    android_package_name: str = "ie.yarodev.pam"
    android_cert_fingerprints: str = ""

    # LLM categorization. Any OpenAI-compatible chat endpoint works; Google's
    # Gemini free tier is the default. Leaving the key unset disables
    # /categorize only.
    llm_api_key: str | None = None
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    llm_model: str = "gemini-3.5-flash"
    llm_timeout_seconds: float = 25.0

    # Reading a receipt photo. Must be a model that accepts images; the
    # default is the same one, which does. Vision calls carry a picture and
    # think for longer, so they get their own, laxer timeout.
    llm_vision_model: str = "gemini-3.5-flash"
    llm_vision_timeout_seconds: float = 45.0
    # Generous, because a reasoning model spends this budget thinking before
    # it writes a character of the answer, and a budget that runs out mid-JSON
    # produces nothing usable. The answer itself is about sixty tokens.
    llm_vision_max_tokens: int = 2000
    # The photo is never stored; this only bounds what one request may cost
    # in memory and in provider tokens. The client downscales before sending,
    # so a normal receipt arrives well under this.
    receipt_max_bytes: int = 4_000_000

    # Converting a foreign receipt to euro. The ECB publishes one reference
    # rate per currency per working day, free and without a key; the file
    # changes once a day, so it is cached for six hours.
    ecb_rates_url: str = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
    # The ECB does not quote the hryvnia, so it comes from its own central
    # bank instead, one date per request.
    nbu_rates_url: str = "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange"
    fx_cache_seconds: float = 21_600.0
    fx_timeout_seconds: float = 6.0


settings = Settings()
