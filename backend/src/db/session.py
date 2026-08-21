from collections.abc import Iterator
from types import TracebackType

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from db.settings import DBSettings
from shared.utils.singleton_util import SingletonMeta


class DatabaseTransaction:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory
        self.session: Session | None = None

    def __enter__(self) -> Session:
        self.session = self.session_factory()
        return self.session

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.session is None:
            return

        try:
            if exc_type is not None:
                self.session.rollback()
        finally:
            self.session.close()


class Database(metaclass=SingletonMeta):
    def __init__(self, settings: DBSettings | None = None) -> None:
        if getattr(self, "_initialized", False):
            return

        self.settings = settings or DBSettings()
        self.engine = create_engine(self.settings.url, pool_pre_ping=True)
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
        )
        self._initialized = True

    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
        finally:
            session.close()

    def transaction(self) -> DatabaseTransaction:
        return DatabaseTransaction(self.session_factory)

    def dispose(self) -> None:
        self.engine.dispose()

    @classmethod
    def create_engine(cls, settings: DBSettings | None = None) -> Engine:
        db_settings = settings or DBSettings()
        return create_engine(db_settings.url, pool_pre_ping=True)
