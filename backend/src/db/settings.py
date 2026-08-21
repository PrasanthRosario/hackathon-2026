from functools import cached_property

from pydantic import SecretStr
from pydantic_settings import BaseSettings
from sqlalchemy.engine import URL


class DBSettings(BaseSettings):
    database_url: str | None = None
    db_driver: str = "postgresql+psycopg"
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "film_set"
    db_user: str = "postgres"
    db_password: SecretStr = SecretStr("postgres")

    @cached_property
    def url(self) -> str:
        if self.database_url:
            return self.database_url

        return URL.create(
            drivername=self.db_driver,
            username=self.db_user,
            password=self.db_password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        ).render_as_string(hide_password=False)
