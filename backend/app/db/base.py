"""SQLAlchemy engine, session factory and the declarative Base class."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Parent class for every table in `models.py`."""


def make_engine(database_url: str | None = None) -> Engine:
    """Create an engine. Defaults to the local SQLite file from settings."""
    if database_url is None:
        settings = get_settings()
        # Make sure the git-ignored data/ folder exists before SQLite opens the file.
        settings.database_path.parent.mkdir(parents=True, exist_ok=True)
        database_url = settings.database_url
    # check_same_thread=False lets FastAPI's worker threads share the connection pool.
    return create_engine(database_url, connect_args={"check_same_thread": False})


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db(bind: Engine = engine) -> None:
    """Create any missing tables. Safe to run repeatedly."""
    from app.db import models  # noqa: F401  (import registers tables on Base)

    Base.metadata.create_all(bind)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed afterwards."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
