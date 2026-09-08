from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Every value comes from the environment (or a
    local .env file); this is the only module that reads it."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    # How long startup will keep retrying the database before giving up.
    db_startup_timeout_seconds: float = 30.0


settings = Settings()
