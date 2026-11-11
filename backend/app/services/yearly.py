"""The budget year at a glance: income, expenses, savings and investing so far,
month by month, with the biggest swings, plus deposits that need explaining.

All figures use the same spending calculation as the rest of the dashboard
(your share of shared costs, the household rent rule, your corrections).

- Income: every deposit classified as income (pay, interest, other earnings).
  A deposit you mark with a spending category (e.g. an employer reimbursement
  marked Education) is not income: it reduces that category instead.
- Expenses: all spending, budgeted or not (rent included).
- Saved = income - expenses.
- Invested: money moved from your accounts into investment / retirement
  accounts (automatic deposits and one-off transfers). Paycheck deductions into
  a workplace 401(k) never pass through your bank, so they aren't included.

Deposits that need explaining: money in from a source that isn't a regular
paycheck or interest (e.g. an employer's "vendor pay"), not yet reviewed by you.
Tell Claude what it is, or mark it yourself:
    python -m app.cli categorize ID Education --note "employer reimbursement"   # reduces Education
    python -m app.cli categorize ID Income --note "one-off bonus"              # counts as income
"""

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Transaction
from app.services.spending import CATEGORIES, RentRule, collect_spending

INVEST_DETAILED = {"TRANSFER_OUT_INVESTMENT_AND_RETIREMENT_FUNDS"}
REVIEW_MIN_CENTS = 10_000      # deposits from $100 up
REVIEW_LOOKBACK_DAYS = 120
REVIEW_DETAILED_SKIP = {"INCOME_SALARY", "INCOME_WAGES", "INCOME_INTEREST_EARNED", "INCOME_RENTAL"}


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _months_between(start: date, end: date) -> list[str]:
    keys, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        keys.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return keys


def year_summary(session: Session, year_start: date, year_end: date, today: date | None = None,
                 rent_rule: RentRule | None = None) -> dict:
    today = today or date.today()
    upto = min(today, year_end)
    col = collect_spending(session, year_start, upto, rent_rule) if upto >= year_start else None

    exp = defaultdict(int)
    inc = defaultdict(int)
    by_cat = defaultdict(int)
    income_sources = defaultdict(int)
    if col:
        for it in col.spend:
            exp[_month_key(it.day)] += it.cents
            by_cat[it.category] += it.cents
        for day, cents, desc in col.income:
            inc[_month_key(day)] += cents
            income_sources[desc] += cents

    invested = defaultdict(int)
    for t in session.scalars(select(Transaction).where(
            Transaction.posted_on >= year_start, Transaction.posted_on <= upto,
            Transaction.amount_cents < 0, Transaction.provider_category_detailed.in_(INVEST_DETAILED))):
        invested[_month_key(t.posted_on)] += -t.amount_cents

    months = []
    for k in _months_between(year_start, year_end):
        first = date(int(k[:4]), int(k[5:]), 1)
        started = first <= upto or k == _month_key(year_start)
        complete = started and (_next_month(first) - timedelta(days=1)) <= upto and first >= year_start
        months.append({
            "month": k, "started": started, "complete": complete,
            "expenses_cents": exp[k], "income_cents": inc[k], "saved_cents": inc[k] - exp[k],
            "invested_cents": invested[k],
            "savings_rate": round((inc[k] - exp[k]) / inc[k], 4) if inc[k] > 0 else None,
        })

    # Swings: month-over-month change in expenses between complete months.
    done = [m for m in months if m["complete"]]
    swings = []
    for a, b in zip(done, done[1:]):
        swings.append({"from": a["month"], "to": b["month"], "change_cents": b["expenses_cents"] - a["expenses_cents"]})
    biggest_up = max(swings, key=lambda s: s["change_cents"], default=None)
    biggest_down = min(swings, key=lambda s: s["change_cents"], default=None)

    total_inc, total_exp = sum(inc.values()), sum(exp.values())
    return {
        "year_start": year_start.isoformat(), "year_end": year_end.isoformat(),
        "through": upto.isoformat(),
        "income_cents": total_inc, "expenses_cents": total_exp, "saved_cents": total_inc - total_exp,
        "savings_rate": round((total_inc - total_exp) / total_inc, 4) if total_inc > 0 else None,
        "invested_cents": sum(invested.values()),
        "by_category": {c: by_cat[c] for c in CATEGORIES if by_cat.get(c)},
        "income_sources": dict(sorted(income_sources.items(), key=lambda x: -x[1])),
        "months": months,
        "average_month_expenses_cents": round(sum(m["expenses_cents"] for m in done) / len(done)) if done else None,
        "highest_month": max(done, key=lambda m: m["expenses_cents"])["month"] if done else None,
        "lowest_month": min(done, key=lambda m: m["expenses_cents"])["month"] if done else None,
        "biggest_increase": biggest_up if biggest_up and biggest_up["change_cents"] > 0 else None,
        "biggest_decrease": biggest_down if biggest_down and biggest_down["change_cents"] < 0 else None,
    }


def _next_month(d: date) -> date:
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def deposits_to_review(session: Session, today: date | None = None,
                       regular_payers: set[str] | None = None) -> list[dict]:
    """Money in that isn't a regular paycheck/interest or a transfer, and you haven't explained yet."""
    today = today or date.today()
    regular = {p.lower() for p in (regular_payers or set())}
    out = []
    for t in session.scalars(select(Transaction).where(
            Transaction.amount_cents >= REVIEW_MIN_CENTS,
            Transaction.posted_on >= today - timedelta(days=REVIEW_LOOKBACK_DAYS),
            Transaction.category.is_(None), Transaction.split_parts.is_(None),
            Transaction.provider_category == "INCOME").order_by(Transaction.posted_on.desc())):
        if t.provider_category_detailed in REVIEW_DETAILED_SKIP or t.description.strip().lower() in regular:
            continue
        out.append({"id": t.id, "date": t.posted_on.isoformat(), "amount_cents": t.amount_cents,
                    "description": t.description, "account": t.account.display_name if t.account else None})
    return out
