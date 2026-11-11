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

from app.db.models import Account, AccountKind, BalanceSnapshot, LoanTerms, PlaidItem, SplitExpense
from app.services.loans import estimate_balance, months_to_payoff
from app.config import data_dir, tracking_start
from app.services.networth import compute_net_worth
from app.services.recurring import detect_recurring, monthly_total_cents
from app.services.budgets import BudgetConfig, budget_progress
from app.services.yearly import deposits_to_review, year_summary
from app.services.spending import CATEGORIES, RentRule, monthly_summary

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


def _iso_date(d: date | None) -> str | None:
    return d.isoformat() if d else None


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


def _year(session: Session, today: date) -> dict | None:
    """Budget-year totals (needs a budget year: data/budgets.json)."""
    cfg = BudgetConfig.load(data_dir() / "budgets.json")
    rule = RentRule.load(data_dir() / "household.json")
    bills = detect_recurring(session, today=today, labels_path=data_dir() / "recurring_labels.json")
    regular = {b.merchant for b in bills if b.kind == "income" and b.source == "detected"}
    review = deposits_to_review(session, today, regular, since=tracking_start())
    if cfg is None:
        return {"summary": None, "review": review}
    return {"summary": year_summary(session, cfg.year_start, cfg.year_end, today, rule), "review": review}


def _budgets(session: Session, today: date) -> dict | None:
    cfg = BudgetConfig.load(data_dir() / "budgets.json")
    if cfg is None:
        return None
    return budget_progress(session, cfg, today, RentRule.load(data_dir() / "household.json"))


def _recurring(session: Session, today: date) -> dict:
    bills = detect_recurring(session, today=today, labels_path=data_dir() / "recurring_labels.json")
    return {
        "monthly_total_cents": monthly_total_cents(bills),  # bills & subscriptions only
        "totals": {k: monthly_total_cents(bills, k) for k in ("income", "bill", "loan", "saving", "planned")},
        "all_monthly_cents": monthly_total_cents(bills, None),
        "bills": [{
            "kind": b.kind, "name": b.name, "category": b.category, "amount_cents": b.amount_cents,
            "account": b.account, "source": b.source, "active": b.active, "note": b.note,
            "next_expected": b.next_expected.isoformat() if b.next_expected else None,
            "set_aside_cents": b.set_aside_cents,
            "cadence": b.cadence, "monthly_cents": b.monthly_cents,
            "paid_this_month": b.paid_this_month,
            "last_charged": b.last_charged.isoformat() if b.last_charged else None,
        } for b in bills],
    }


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
    start = tracking_start()
    months = monthly_summary(session, months=6, today=today,
                             rent_rule=RentRule.load(data_dir() / "household.json"))
    history = net_worth_history(session)
    if start:  # show nothing from before you started tracking
        start_key = f"{start.year:04d}-{start.month:02d}"
        months = [m for m in months if m["month"] >= start_key]
        history = [h for h in history if h["date"] >= start.isoformat()]
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
        "history": history,
        "tracking_start": start.isoformat() if start else None,
        "recurring": _recurring(session, today),
        "budgets": _budgets(session, today),
        "year": _year(session, today),
        "spending": {
            "categories": CATEGORIES,
            "months": months,
            # Earliest Splitwise expense imported: shares are applied from here on.
            "shared_from": _iso_date(session.scalar(select(func.min(SplitExpense.spent_on)))),
        },
    }
