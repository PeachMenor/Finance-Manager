"""A short settle-up reminder built from the latest Splitwise balances.

Fits a phone notification (under 200 characters): who you should pay and who
should pay you, biggest first, plus a warning when the balances are out of date
(older than a week means a fresh Splitwise screenshot is due).
"""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import PersonBalance

MAX_CHARS = 200
STALE_AFTER_DAYS = 8


def _short(cents: int) -> str:
    return f"${round(abs(cents) / 100):,}"


def _first(name: str) -> str:
    return name.split()[0]


def _list(rows: list[PersonBalance], limit: int) -> str:
    shown = ", ".join(f"{_first(p.name)} {_short(p.amount_cents)}" for p in rows[:limit])
    rest = len(rows) - limit
    return shown + (f" +{rest} more" if rest > 0 else "")


def build_nudge(session: Session, now: datetime | None = None, currency: str = "USD") -> str | None:
    """The reminder text, or None when there's nothing to settle."""
    now = now or datetime.now(timezone.utc)
    rows = session.scalars(select(PersonBalance).where(PersonBalance.currency == currency)).all()
    pay = sorted((p for p in rows if p.amount_cents < 0), key=lambda p: p.amount_cents)
    collect = sorted((p for p in rows if p.amount_cents > 0), key=lambda p: -p.amount_cents)
    if not pay and not collect:
        return None

    updated = session.scalar(select(func.max(PersonBalance.updated_at)))
    if updated and updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    age = (now - updated).days if updated else None
    stale = f" Balances {age}d old: send a new Splitwise screenshot." if age and age >= STALE_AFTER_DAYS else ""

    total_pay = _short(sum(p.amount_cents for p in pay))
    total_collect = _short(sum(p.amount_cents for p in collect))
    # Show as many names as fit, starting generous and trimming until it fits.
    for limit in (3, 2, 1, 0):
        parts = []
        if pay:
            parts.append(f"Pay {total_pay}" + (f": {_list(pay, limit)}" if limit else ""))
        if collect:
            parts.append(f"Collect {total_collect}" + (f": {_list(collect, limit)}" if limit else ""))
        text = "Splitwise: " + ". ".join(parts) + "." + stale
        if len(text) <= MAX_CHARS:
            return text
    return text[: MAX_CHARS - 1] + "…"


def build_pay_one(session: Session, now: datetime | None = None, currency: str = "USD") -> str | None:
    """Friday reminder: settle with ONE person this week, biggest debt first.

    Next week's screenshot shows them settled, so the next person comes up.
    Also mentions the biggest amount owed to you, as a prompt to ask for it.
    """
    now = now or datetime.now(timezone.utc)
    rows = session.scalars(select(PersonBalance).where(PersonBalance.currency == currency)).all()
    pay = sorted((p for p in rows if p.amount_cents < 0), key=lambda p: p.amount_cents)
    collect = sorted((p for p in rows if p.amount_cents > 0), key=lambda p: -p.amount_cents)
    if not pay and not collect:
        return None
    parts = []
    if pay:
        first, rest = pay[0], pay[1:]
        parts.append(f"This week, pay {_first(first.name)} {_short(first.amount_cents)} on Splitwise")
        if rest:
            parts.append(f"{len(rest)} more after that ({_short(sum(p.amount_cents for p in rest))})")
    else:
        parts.append("You don't owe anyone on Splitwise")
    if collect:
        parts.append(f"Ask {_first(collect[0].name)} for {_short(collect[0].amount_cents)}")
    updated = session.scalar(select(func.max(PersonBalance.updated_at)))
    if updated and updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    if updated and (now - updated).days >= STALE_AFTER_DAYS:
        parts.append("Send a new screenshot")
    text = ". ".join(parts) + "."
    return text if len(text) <= MAX_CHARS else text[: MAX_CHARS - 1] + "…"
