from collections.abc import Generator

from fastapi import Request
from sqlalchemy.orm import Session

from db.database import database


def get_db_session(request: Request) -> Generator[Session, None, None]:
    request_session = getattr(request.state, "db", None)
    if request_session is not None:
        yield request_session
        return

    yield from database.session()
