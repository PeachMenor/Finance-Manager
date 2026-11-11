"""Everything the one-page dashboard shows, in one call.

Sections (counted accounts only, unless noted):
- Cash & savings: checking, savings, cash
- Investments: brokerage, retirement (if counted), HSA, crypto, other
- Credit cards and Loans: amounts owed (subtracted)
- People: Splitwise balances
- Shown, not counted: accounts excluded from net worth (e.g. 401k, unvested awards)
- Net worth history: one point per day, from the balance history every sync records

Hidden accounts are left out of the lists but still included in every total.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Account, AccountKind, BalanceSnapshot, LoanTerms, PlaidItem
from app.services.loans import estimate_balance, months_to_payoff
from app.services.networth import compute_net_worth

GROUPS = [
    ("cash", "Cash & savings", {AccountKind.CHECKING, AccountKind.SAVINGS, AccountKind.CASH}),
    ("investments", "Investments", {AccountKind.BROKERAGE, AccountKind.RETIREMENT, AccountKind.HSA,
                                    AccountKind.CRYPTO, AccountKind.OTHER}),
    ("cards", "Credit cards", {AccountKind.CREDIT_CARD}),
    ("loans", "Loans", {AccountKind.LOAN}),
]


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:  # SQLite drops the zone; values are stored in UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _account_row(a: Account) -> dict:
    return {
        "id": a.id,
        "name": a.display_name,
        "institution": a.institution.name if a.institution else None,
        "kind": a.kind.value,
        "balance_cents": a.balance_cents,
    }


def net_worth_history(session: Session, currency: str = "USD") -> list[dict]:
    """Daily net worth from balance snapshots, for accounts that count today.

    For each day, each account contributes its LAST recorded balance on or before
    that day (accounts with no history yet are skipped until their first one).
    Splitwise balances have no history and are left out of past days.
    """
    accounts = {
        a.id: a
        for a in session.scalars(
            select(Account).where(Account.currency == currency, Account.include_in_net_worth.is_(True))
        )
    }
    if not accounts:
        return []
    snaps = session.execute(
        select(BalanceSnapshot.account_id, BalanceSnapshot.taken_at, BalanceSnapshot.balance_cents)
        .where(BalanceSnapshot.account_id.in_(accounts))
        .order_by(BalanceSnapshot.taken_at)
    ).all()
    if not snaps:
        return []

    # Last balance per account per LOCAL day (times are stored in UTC; an evening
    # sync in California is already "tomorrow" in UTC).
    per_day: dict[date, dict[int, int]] = defaultdict(dict)
    for account_id, taken_at, cents in snaps:
        if taken_at.tzinfo is None:
            taken_at = taken_at.replace(tzinfo=timezone.utc)
        per_day[taken_at.astimezone().date()][account_id] = cents

    history, latest = [], {}
    today = datetime.now().date()
    day, last_day = min(per_day), max(max(per_day), today)
    while day <= last_day:
        latest.update(per_day.get(day, {}))
        total = sum(-c if accounts[i].kind.is_liability else c for i, c in latest.items())
        history.append({"date": day.isoformat(), "net_worth_cents": total})
        day += timedelta(days=1)
    # Today's point is always the live figure, so the chart and the headline agree
    # (it covers accounts with no history yet and Splitwise balances).
    if history and history[-1]["date"] == today.isoformat():
        history[-1]["net_worth_cents"] = compute_net_worth(session, currency).net_worth_cents
    return history


def build_dashboard(session: Session, today: date | None = None) -> dict:
    today = today or date.today()
    s = compute_net_worth(session)
    accounts = session.scalars(select(Account).order_by(Account.balance_cents.desc())).all()

    groups = []
    for key, label, kinds in GROUPS:
        members = [a for a in accounts if a.kind in kinds and a.include_in_net_worth and a.currency == "USD"]
        groups.append({
            "key": key,
            "label": label,
            "total_cents": sum(a.balance_cents for a in members),  # includes hidden ones
            "accounts": [_account_row(a) for a in members if not a.hidden],
        })

    not_counted = [_account_row(a) for a in accounts if not a.include_in_net_worth]

    loans = []
    for t in session.scalars(select(LoanTerms)).all():
        est = estimate_balance(t, today, session)
        loans.append({
            "account_id": t.account_id,
            "name": t.account.display_name,
            "balance_cents": est.balance_cents,
            "apr_percent": t.apr_bps / 100,
            "regular_payment_cents": t.monthly_payment_cents,
            "payments_left": months_to_payoff(t, est.balance_cents),
            "maturity_date": t.maturity_date.isoformat() if t.maturity_date else None,
        })

    last_synced = session.scalar(select(func.max(PlaidItem.last_synced_at)))
    return {
        "as_of": _iso(last_synced),
        "net_worth_cents": s.net_worth_cents,
        "assets_cents": s.assets_cents,
        "liabilities_cents": s.liabilities_cents,
        "owed_to_you_cents": s.owed_to_you_cents,
        "you_owe_cents": s.you_owe_cents,
        "groups": groups,
        "not_counted": {"total_cents": s.excluded_cents, "accounts": not_counted},
        "people": [{"name": n, "amount_cents": c} for n, c in s.people],
        "loans": loans,
        "history": net_worth_history(session),
    }
