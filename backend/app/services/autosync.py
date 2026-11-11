"""Sync everything, by hand ("Sync now") or automatically while the server runs.

Automatic sync:
- Runs shortly after the server starts, then every FM_AUTO_SYNC_HOURS hours
  (default 6; set 0 in .env to turn it off). Each Plaid request may count toward
  your Plaid bill once past any free allowance, so it is deliberately not
  minute-by-minute.
- Only runs while the server is running; it is not a background service.
- One failing login doesn't stop the others; errors are recorded, never raised.

A lock makes sure a manual "Sync now" and an automatic run never overlap, which
could otherwise try to insert the same transaction twice.
"""

import asyncio
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PlaidItem
from app.integrations.plaid import PlaidError
from app.services.loans import refresh_manual_loans
from app.services.sync import sync_plaid_item

log = logging.getLogger("finance.sync")
SYNC_LOCK = threading.Lock()
DEFAULT_HOURS = 6.0


@dataclass
class ItemResult:
    item: PlaidItem
    institution: str | None  # captured up front: a rollback expires `item`'s fields
    ok: bool
    new_transactions: int = 0
    error: str | None = None


def sync_everything(session: Session, client) -> list[ItemResult]:
    """Sync every linked Plaid login, then refresh hand-entered loans."""
    results = []
    with SYNC_LOCK:
        for item in session.scalars(select(PlaidItem).order_by(PlaidItem.id)).all():
            name = item.institution_name
            try:
                r = sync_plaid_item(session, client, item)
                results.append(ItemResult(item, item.institution_name, True, r.new_transactions))
            except PlaidError as e:
                session.rollback()
                results.append(ItemResult(item, name, False, error=e.error_code))
        refresh_manual_loans(session)  # loans move with payments found in new transactions
    return results


def auto_sync_hours() -> float:
    """Hours between automatic syncs; 0 means off."""
    try:
        return max(0.0, float(os.getenv("FM_AUTO_SYNC_HOURS", DEFAULT_HOURS)))
    except ValueError:
        return DEFAULT_HOURS


@dataclass
class AutoSyncState:
    every_hours: float = 0.0
    running: bool = False
    last_finished_at: datetime | None = None
    last_ok: bool | None = None
    last_message: str = ""
    history: list[str] = field(default_factory=list)  # short log, newest last

    def view(self) -> dict:
        return {
            "every_hours": self.every_hours,
            "running": self.running,
            "last_finished_at": self.last_finished_at.isoformat() if self.last_finished_at else None,
            "last_ok": self.last_ok,
            "last_message": self.last_message,
        }


STATE = AutoSyncState()


def run_once(session_factory, client_factory, state: AutoSyncState = STATE) -> None:
    """One automatic sync. Never raises: the outcome goes into `state` and the log."""
    try:
        client = client_factory()
        with session_factory() as session:
            results = sync_everything(session, client)
        failed = [f"{r.institution or 'a login'} ({r.error})" for r in results if not r.ok]
        new = sum(r.new_transactions for r in results)
        state.last_ok = not failed
        state.last_message = (
            f"{len(results)} logins, {new} new transactions"
            + (f"; problems: {', '.join(failed)}" if failed else "")
        )
    except Exception as e:  # e.g. network down; try again next time
        state.last_ok = False
        state.last_message = f"failed: {type(e).__name__}"
    state.last_finished_at = datetime.now(timezone.utc)
    state.history = (state.history + [state.last_message])[-20:]
    log.info("auto-sync: %s", state.last_message)


async def auto_sync_loop(session_factory, client_factory, hours: float, first_delay: float = 5.0,
                         state: AutoSyncState = STATE) -> None:
    """Sync soon after start, then every `hours`. Cancelled when the server stops."""
    state.every_hours, state.running = hours, True
    try:
        await asyncio.sleep(first_delay)  # let the server finish starting first
        while True:
            # Sync is blocking (network + database), so run it in a worker thread.
            await asyncio.to_thread(run_once, session_factory, client_factory, state)
            await asyncio.sleep(hours * 3600)
    finally:
        state.running = False
