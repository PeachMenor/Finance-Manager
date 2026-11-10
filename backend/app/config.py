"""App settings, read from environment variables / the local `.env` file.

Secrets (API keys, access URLs) are only ever read from the environment.
They are never hard-coded and never written to the database or logs.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Repo root = two levels up from this file (backend/app/config.py -> repo/).
REPO_ROOT = Path(__file__).resolve().parents[2]

# Load `.env` from the repo root if present. Real environment variables win.
load_dotenv(REPO_ROOT / ".env", override=False)


@dataclass(frozen=True)
class Settings:
    # Where the local SQLite database lives. `data/` is git-ignored, so
    # your financial data never ends up in the repo.
    database_path: Path

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"


def get_settings() -> Settings:
    """Build settings from the environment (called fresh so tests can override)."""
    db_path = Path(os.getenv("FM_DATABASE_PATH", REPO_ROOT / "data" / "finance.db"))
    return Settings(database_path=db_path)
