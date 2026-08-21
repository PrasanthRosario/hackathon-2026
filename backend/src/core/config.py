from pydantic_settings import SettingsConfigDict

from db.settings import DBSettings


class Settings(DBSettings):
    app_name: str = "Film set"
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="FILM_SET_",
        extra="ignore",
    )


settings = Settings()
