"""SQLAlchemy engine, session factory and the declarative Base class."""

from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
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
    """Create missing tables and add missing columns. Safe to run repeatedly."""
    from app.db import models  # noqa: F401  (import registers tables on Base)

    Base.metadata.create_all(bind)
    _add_missing_columns(bind)
    _migrate_category_names(bind)


def _migrate_category_names(bind: Engine) -> None:
    """Rename stored categories that were renamed in code (safe to repeat)."""
    import json

    from app.services.spending import CATEGORY_ALIASES

    def fix_json(raw: str | None) -> str | None:
        if not raw:
            return raw
        parts: dict[str, int] = {}
        for k, v in json.loads(raw).items():
            k = CATEGORY_ALIASES.get(k, k)
            parts[k] = parts.get(k, 0) + v
        return json.dumps(parts)

    with bind.begin() as conn:
        for old, new in CATEGORY_ALIASES.items():
            for table in ("transactions", "split_expenses", "manual_recurring"):
                conn.execute(text(f'UPDATE "{table}" SET category = :new WHERE category = :old'),
                             {"old": old, "new": new})
        for table in ("transactions", "split_expenses"):
            rows = conn.execute(text(f'SELECT id, split_parts FROM "{table}" WHERE split_parts IS NOT NULL')).all()
            for row_id, raw in rows:
                fixed = fix_json(raw)
                if fixed != raw:
                    conn.execute(text(f'UPDATE "{table}" SET split_parts = :p WHERE id = :i'), {"p": fixed, "i": row_id})


def _add_missing_columns(bind: Engine) -> None:
    """Lightweight upgrade for existing databases.

    `create_all` makes new tables but never changes existing ones. When a new
    optional column is added to a model, this adds it to your existing database
    (keeping all data). Only nullable columns are added automatically; anything
    more complex would need a proper migration.
    """
    inspector = inspect(bind)
    with bind.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                if not col.nullable:
                    raise RuntimeError(
                        f"Column {table.name}.{col.name} is required and missing; "
                        "it needs a manual migration."
                    )
                col_type = col.type.compile(dialect=bind.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col_type}'))


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed afterwards."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
