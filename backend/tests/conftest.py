"""Test setup: point the app at a throwaway database so tests never touch real data.

This must run before `app` is imported, because the engine is created at import time.
"""

import os
import tempfile
from pathlib import Path

_TMP_DIR = tempfile.mkdtemp(prefix="fm-test-")
os.environ["FM_DATABASE_PATH"] = str(Path(_TMP_DIR) / "test.db")

import pytest  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.base import Base, SessionLocal, engine, init_db  # noqa: E402


@pytest.fixture()
def session() -> Session:
    """A fresh, empty database for each test."""
    Base.metadata.drop_all(engine)
    init_db(engine)
    with SessionLocal() as s:
        yield s
