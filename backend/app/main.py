"""FastAPI entry point. Run with:  uvicorn app.main:app --reload  (from backend/).

Security: this server holds your financial data and has no login, so it must only
be reachable from this computer.
- uvicorn listens on 127.0.0.1 by default. Never start it with --host 0.0.0.0.
- TrustedHostMiddleware rejects requests whose Host isn't localhost/127.0.0.1. That
  blocks "DNS rebinding", where a malicious website tricks your browser into
  reading a local server.
"""

import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.plaid import router as plaid_router
from app.db.base import SessionLocal, get_session, init_db
from app.integrations.plaid import PlaidClient
from app.services.autosync import auto_sync_hours, auto_sync_loop
from app.db.models import Account
from app.services.networth import compute_net_worth

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

STATIC_DIR = Path(__file__).parent / "static"
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Create tables on startup so a fresh clone works without a migration step.
    init_db()
    task = None
    hours = auto_sync_hours()
    if hours > 0 and os.getenv("PLAID_CLIENT_ID") and os.getenv("PLAID_SECRET"):
        task = asyncio.create_task(auto_sync_loop(SessionLocal, PlaidClient.from_env, hours))
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Finance Manager", lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
app.include_router(plaid_router)


@app.get("/link", include_in_schema=False)
def link_page() -> FileResponse:
    """The page for linking bank logins through Plaid."""
    return FileResponse(STATIC_DIR / "link.html")


@app.get("/health")
def health() -> dict:
    """Simple check that the server is up."""
    return {"status": "ok"}


@app.get("/accounts")
def list_accounts(session: Session = Depends(get_session)) -> list[dict]:
    """All accounts with their latest balance (in cents)."""
    accounts = session.scalars(select(Account).order_by(Account.name)).all()
    return [
        {
            "id": a.id,
            "name": a.display_name,
            "institution": a.institution.name if a.institution else None,
            "kind": a.kind.value,
            "balance_cents": a.balance_cents,
            "currency": a.currency,
            "hidden": bool(a.hidden),
        }
        for a in accounts
    ]


@app.get("/summary")
def summary(session: Session = Depends(get_session)) -> dict:
    """Net worth breakdown: assets, liabilities, Splitwise balances, total."""
    s = compute_net_worth(session)
    return {
        "net_worth_cents": s.net_worth_cents,
        "assets_cents": s.assets_cents,
        "liabilities_cents": s.liabilities_cents,
        "owed_to_you_cents": s.owed_to_you_cents,
        "you_owe_cents": s.you_owe_cents,
        "excluded_cents": s.excluded_cents,
        "people": [{"name": n, "amount_cents": c} for n, c in s.people],
    }
