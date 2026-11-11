"""Routes for linking, listing, syncing and unlinking Plaid logins.

Flow when you link a login:
  1. The page asks POST /plaid/link-token for a short-lived token.
  2. Plaid's own pop-up (Plaid Link) opens; you sign in to your bank THERE.
     This app never sees your bank username or password.
  3. Plaid hands the page a one-time `public_token`; the page sends it to
     POST /plaid/exchange, which swaps it for a lasting access token,
     stores it in the local database and runs a first sync.

Access tokens never leave the server: no route returns them.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import get_session
from app.db.models import PlaidItem
from app.integrations.plaid import PlaidClient, PlaidError
from app.services.loans import refresh_manual_loans
from app.services.sync import sync_plaid_item

router = APIRouter(prefix="/plaid", tags=["plaid"])


def get_plaid_client() -> PlaidClient:
    """Dependency; tests replace it with a fake Plaid server."""
    try:
        return PlaidClient.from_env()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


class LinkTokenRequest(BaseModel):
    kind: str = "banking"  # "banking" or "investments"


class ExchangeRequest(BaseModel):
    public_token: str


def _utc_iso(dt: datetime | None) -> str | None:
    """ISO time with an explicit UTC offset.

    SQLite drops timezone info, so times come back "naive". They were saved in
    UTC; without the offset the browser would read them as local time.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _item_view(item: PlaidItem) -> dict:
    return {
        "id": item.id,
        "institution": item.institution_name,
        "last_synced_at": _utc_iso(item.last_synced_at),
    }


def _plaid_failure(e: PlaidError) -> HTTPException:
    # Pass Plaid's error code through (e.g. ITEM_LOGIN_REQUIRED) so the page can explain it.
    return HTTPException(status_code=502, detail=f"Plaid: {e.error_code}")


@router.get("/status")
def status(client: PlaidClient = Depends(get_plaid_client)) -> dict:
    """Which Plaid environment the server is using (sandbox = fake banks)."""
    return {"env": client.env}


@router.post("/link-token")
def link_token(req: LinkTokenRequest, client: PlaidClient = Depends(get_plaid_client)) -> dict:
    if req.kind not in ("banking", "investments"):
        raise HTTPException(status_code=400, detail="kind must be 'banking' or 'investments'")
    try:
        return {"link_token": client.create_link_token(req.kind)}
    except PlaidError as e:
        raise _plaid_failure(e) from e


@router.post("/exchange")
def exchange(
    req: ExchangeRequest,
    session: Session = Depends(get_session),
    client: PlaidClient = Depends(get_plaid_client),
) -> dict:
    try:
        item_id, access_token = client.exchange_public_token(req.public_token)
    except PlaidError as e:
        raise _plaid_failure(e) from e

    # Re-linking the same login replaces its token instead of adding a duplicate.
    item = session.scalar(select(PlaidItem).where(PlaidItem.item_id == item_id))
    if item is None:
        item = PlaidItem(item_id=item_id, access_token=access_token)
        session.add(item)
    else:
        item.access_token = access_token
    session.commit()

    try:
        result = sync_plaid_item(session, client, item)
    except PlaidError as e:
        # Linked fine but the first sync failed; it can be retried with "Sync now".
        return {"item": _item_view(item), "synced": False, "error": e.error_code}
    return {
        "item": _item_view(item),
        "synced": True,
        "accounts": result.accounts,
        "new_transactions": result.new_transactions,
    }


@router.get("/items")
def list_items(session: Session = Depends(get_session)) -> list[dict]:
    return [_item_view(i) for i in session.scalars(select(PlaidItem).order_by(PlaidItem.id))]


@router.post("/sync")
def sync_all(
    session: Session = Depends(get_session),
    client: PlaidClient = Depends(get_plaid_client),
) -> dict:
    """Sync every linked login. One failing login doesn't stop the others."""
    results = []
    for item in session.scalars(select(PlaidItem).order_by(PlaidItem.id)).all():
        try:
            r = sync_plaid_item(session, client, item)
            results.append({**_item_view(item), "ok": True, "new_transactions": r.new_transactions})
        except PlaidError as e:
            session.rollback()
            results.append({**_item_view(item), "ok": False, "error": e.error_code})
    refresh_manual_loans(session)  # hand-entered loans move with each payment date
    return {"items": results}


@router.delete("/items/{item_pk}")
def unlink(
    item_pk: int,
    session: Session = Depends(get_session),
    client: PlaidClient = Depends(get_plaid_client),
) -> dict:
    """Revoke access at Plaid and forget the token. Synced history is kept."""
    item = session.get(PlaidItem, item_pk)
    if item is None:
        raise HTTPException(status_code=404, detail="No such linked login")
    try:
        client.remove_item(item.access_token)
    except PlaidError as e:
        if e.error_code != "ITEM_NOT_FOUND":  # already gone at Plaid: just forget it
            raise _plaid_failure(e) from e
    session.delete(item)
    session.commit()
    return {"removed": item_pk}
