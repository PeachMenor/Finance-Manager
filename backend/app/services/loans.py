"""Estimate a hand-entered loan's balance between statements.

Model (a close approximation of a typical fixed-rate auto loan):
- One payment per month, on `payment_day`.
- Each payment first covers one month of interest (balance x APR / 12, rounded
  to the cent), and the rest reduces the principal.
- The balance never goes below zero.

Real lenders often accrue interest daily, so the estimate can drift by a few
dollars over several months. Each new statement resets it to the exact figure.
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import BalanceSnapshot, LoanTerms


def payment_dates(after: date, until: date, day: int) -> list[date]:
    """Payment dates strictly after `after` and on or before `until`."""
    dates = []
    y, m = after.year, after.month
    while True:
        d = date(y, m, day)
        if d > until:
            return dates
        if d > after:
            dates.append(d)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def monthly_interest_cents(balance_cents: int, apr_bps: int) -> int:
    interest = Decimal(balance_cents) * Decimal(apr_bps) / Decimal(10_000) / Decimal(12)
    return int(interest.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass
class LoanEstimate:
    balance_cents: int
    payments_applied: int
    interest_paid_cents: int


def estimate_balance(terms: LoanTerms, today: date) -> LoanEstimate:
    balance = terms.principal_cents
    interest_total = 0
    dates = payment_dates(terms.balance_as_of, today, terms.payment_day)
    for _ in dates:
        if balance <= 0:
            break
        interest = monthly_interest_cents(balance, terms.apr_bps)
        interest_total += interest
        balance = max(0, balance + interest - terms.monthly_payment_cents)
    return LoanEstimate(balance, len(dates), interest_total)


def months_to_payoff(terms: LoanTerms, from_balance_cents: int) -> int | None:
    """Payments left at the current rate, or None if the payment doesn't cover interest."""
    balance, months = from_balance_cents, 0
    while balance > 0:
        interest = monthly_interest_cents(balance, terms.apr_bps)
        if terms.monthly_payment_cents <= interest:
            return None
        balance = max(0, balance + interest - terms.monthly_payment_cents)
        months += 1
    return months


def refresh_manual_loans(session: Session, today: date | None = None) -> int:
    """Update every hand-entered loan's balance from its terms. Returns how many changed."""
    today = today or date.today()
    now = datetime.now(timezone.utc)
    changed = 0
    for terms in session.scalars(select(LoanTerms)).all():
        est = estimate_balance(terms, today)
        acct = terms.account
        if acct.balance_cents != est.balance_cents:
            acct.balance_cents = est.balance_cents
            session.add(BalanceSnapshot(account=acct, balance_cents=est.balance_cents, taken_at=now))
            changed += 1
        acct.balance_updated_at = now
    session.commit()
    return changed
