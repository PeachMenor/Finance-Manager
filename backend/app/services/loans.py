"""Estimate a hand-entered loan's balance between statements.

The starting point is always an exact figure from a statement: the principal
owed on `balance_as_of`. From there, two ways to move it forward:

1. Tracked payments (when `payment_match` is set) - the most accurate.
   Payments to the lender are found in your synced bank transactions. Each one
   first pays the interest accrued DAILY since the previous payment
   (balance x APR / 365 x days), and the rest reduces the principal. This is how
   simple-interest auto loans work, so it follows irregular amounts and dates.

2. Scheduled payments (no `payment_match`) - an approximation.
   Assumes the regular payment is made every month on `payment_day`, with one
   month of interest (balance x APR / 12) charged first.

In both cases the balance never goes below zero, and entering a newer statement
resets it to the exact figure.

Known limit: if you tell the lender to apply a payment to principal only, the
lender's split differs from this model until the next statement is entered.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import BalanceSnapshot, LoanTerms, Transaction


def _cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def payment_dates(after: date, until: date, day: int) -> list[date]:
    """Scheduled payment dates strictly after `after` and on or before `until`."""
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
    return _cents(Decimal(balance_cents) * Decimal(apr_bps) / Decimal(10_000) / Decimal(12))


def daily_interest_cents(balance_cents: int, apr_bps: int, days: int) -> int:
    return _cents(Decimal(balance_cents) * Decimal(apr_bps) / Decimal(10_000) / Decimal(365) * days)


@dataclass
class LoanPayment:
    effective_on: date  # when the lender credited it (bank date minus posting lag)
    amount_cents: int  # positive


@dataclass
class LoanEstimate:
    balance_cents: int
    payments_applied: int
    interest_paid_cents: int
    payments: list[LoanPayment] = field(default_factory=list)


def find_tracked_payments(session: Session, terms: LoanTerms, today: date) -> list[LoanPayment]:
    """Payments to this lender in bank transactions, credited after the statement date.

    A payment the bank posts a day or two after the statement date can belong to
    the statement itself; the posting lag shifts it back to the lender's date so
    it isn't counted twice.
    """
    if not terms.payment_match:
        return []
    lag = timedelta(days=terms.posting_lag_days or 0)
    rows = session.scalars(
        select(Transaction).where(
            func.lower(Transaction.description).contains(terms.payment_match.lower()),
            Transaction.amount_cents < 0,  # money leaving your bank account
            Transaction.account_id != terms.account_id,
        )
    ).all()
    payments = [LoanPayment(t.posted_on - lag, -t.amount_cents) for t in rows]
    return sorted(
        (p for p in payments if terms.balance_as_of < p.effective_on <= today),
        key=lambda p: p.effective_on,
    )


def _apply_tracked(terms: LoanTerms, payments: list[LoanPayment]) -> LoanEstimate:
    balance, interest_total, last = terms.principal_cents, 0, terms.balance_as_of
    owed_interest = terms.unpaid_interest_cents or 0  # carried in from the statement
    for p in payments:
        if balance <= 0:
            break
        owed_interest += daily_interest_cents(balance, terms.apr_bps, (p.effective_on - last).days)
        to_interest = min(owed_interest, p.amount_cents)  # interest is always paid first
        owed_interest -= to_interest  # a payment smaller than the interest leaves the rest owed
        interest_total += to_interest
        balance = max(0, balance - (p.amount_cents - to_interest))
        last = p.effective_on
    return LoanEstimate(balance, len(payments), interest_total, payments)


def _apply_scheduled(terms: LoanTerms, today: date) -> LoanEstimate:
    balance, interest_total = terms.principal_cents, 0
    dates = payment_dates(terms.balance_as_of, today, terms.payment_day)
    for _ in dates:
        if balance <= 0:
            break
        interest = monthly_interest_cents(balance, terms.apr_bps)
        interest_total += interest
        balance = max(0, balance + interest - terms.monthly_payment_cents)
    return LoanEstimate(balance, len(dates), interest_total)


def estimate_balance(terms: LoanTerms, today: date, session: Session | None = None) -> LoanEstimate:
    """Tracked payments if configured (needs `session`), otherwise the monthly schedule."""
    if terms.payment_match and session is not None:
        return _apply_tracked(terms, find_tracked_payments(session, terms, today))
    return _apply_scheduled(terms, today)


def months_to_payoff(terms: LoanTerms, from_balance_cents: int) -> int | None:
    """Regular payments left, or None if the payment doesn't cover interest."""
    balance, months = from_balance_cents, 0
    while balance > 0:
        interest = monthly_interest_cents(balance, terms.apr_bps)
        if terms.monthly_payment_cents <= interest:
            return None
        balance = max(0, balance + interest - terms.monthly_payment_cents)
        months += 1
    return months


def refresh_manual_loans(session: Session, today: date | None = None) -> int:
    """Update every hand-entered loan's balance. Returns how many changed."""
    today = today or date.today()
    now = datetime.now(timezone.utc)
    changed = 0
    for terms in session.scalars(select(LoanTerms)).all():
        est = estimate_balance(terms, today, session)
        acct = terms.account
        if acct.balance_cents != est.balance_cents:
            acct.balance_cents = est.balance_cents
            session.add(BalanceSnapshot(account=acct, balance_cents=est.balance_cents, taken_at=now))
            changed += 1
        acct.balance_updated_at = now
    session.commit()
    return changed
