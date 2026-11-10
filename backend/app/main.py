"""FastAPI entry point. Run with:  uvicorn app.main:app --reload  (from backend/)."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import get_session, init_db
from app.db.models import Account
from app.services.networth import compute_net_worth


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Create tables on startup so a fresh clone works without a migration step.
    init_db()
    yield


app = FastAPI(title="Finance Manager", lifespan=lifespan)


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
            "name": a.name,
            "institution": a.institution.name if a.institution else None,
            "kind": a.kind.value,
            "balance_cents": a.balance_cents,
            "currency": a.currency,
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
