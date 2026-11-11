"""Monthly spending, income and savings rate from transactions.

Every transaction is one of:
- spending:  money out (or a refund back in) in a spending category
- income:    paychecks and other earnings
- transfer:  money moving between your own accounts or toward a debt you already
             count: card payments, loan payments, transfers. Never counted as
             spending, otherwise a card purchase would count twice (once when
             bought, again when the bill is paid).

Spending categories come from the provider (Plaid's personal finance categories),
unless you've set your own `category` on a transaction.

Refunds (money back in a spending category) reduce that category.

Rent paid through a rent-rewards card shows up three times: the bank payment to
the card company (labelled rent), and on the card both a credit (labelled rental
income) and the rent charge. The credit is treated as reducing Rent, which
cancels one of the two rent entries so rent counts exactly once. (Money from
housemates labelled rental income would also, correctly, reduce Rent.)

Known limits until Stage 3:
- Shared purchases count in full; your Splitwise share is applied in Stage 3.
- Loan payments are all treated as transfers; their interest isn't counted yet.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Transaction

# Display order is fixed so each category keeps the same colour everywhere.
CATEGORIES = [
    "Rent", "Food", "Shopping", "Transport", "Entertainment", "Travel", "Bills & utilities", "Other",
]

_PRIMARY_TO_CATEGORY = {
    "FOOD_AND_DRINK": "Food",
    "GENERAL_MERCHANDISE": "Shopping",
    "HOME_IMPROVEMENT": "Shopping",
    "TRANSPORTATION": "Transport",
    "ENTERTAINMENT": "Entertainment",
    "TRAVEL": "Travel",
    "RENT_AND_UTILITIES": "Bills & utilities",  # rent itself is picked out below
    "MEDICAL": "Other",
    "PERSONAL_CARE": "Other",
    "GENERAL_SERVICES": "Other",
    "GOVERNMENT_AND_NON_PROFIT": "Other",
    "BANK_FEES": "Other",
}
_TRANSFER_PRIMARIES = {"TRANSFER_IN", "TRANSFER_OUT", "LOAN_PAYMENTS"}


@dataclass
class Classified:
    kind: str  # "spending" | "income" | "transfer"
    category: str | None = None


def classify(primary: str | None, detailed: str | None, amount_cents: int,
             user_category: str | None = None) -> Classified:
    """Decide what a transaction means for spending and savings."""
    if user_category:
        if user_category in ("Income", "Transfer"):
            return Classified(user_category.lower())
        return Classified("spending", user_category)
    if primary in _TRANSFER_PRIMARIES:
        return Classified("transfer")
    if primary == "INCOME":
        if detailed == "INCOME_RENTAL":  # cancels a duplicate rent entry (see module docstring)
            return Classified("spending", "Rent")
        return Classified("income") if amount_cents > 0 else Classified("transfer")
    if detailed == "RENT_AND_UTILITIES_RENT":
        return Classified("spending", "Rent")
    if primary in _PRIMARY_TO_CATEGORY:
        return Classified("spending", _PRIMARY_TO_CATEGORY[primary])
    # Unknown or missing category: money out is spending, money in is left out.
    return Classified("spending", "Other") if amount_cents < 0 else Classified("transfer")


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def monthly_summary(session: Session, months: int = 6, today: date | None = None) -> list[dict]:
    """The last `months` calendar months (oldest first), each with:
    spending_cents, income_cents, saved_cents, savings_rate (None without income),
    by_category {name: cents}, first_data_day / partial flags.
    """
    today = today or date.today()
    keys = []
    y, m = today.year, today.month
    for _ in range(months):
        keys.append(f"{y:04d}-{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    keys.reverse()

    spending = {k: defaultdict(int) for k in keys}
    income = dict.fromkeys(keys, 0)
    first_day: dict[str, date] = {}
    earliest = date(int(keys[0][:4]), int(keys[0][5:]), 1)
    rows = session.scalars(select(Transaction).where(Transaction.posted_on >= earliest)).all()
    for t in rows:
        k = _month_key(t.posted_on)
        if k not in spending:
            continue
        first_day[k] = min(first_day.get(k, t.posted_on), t.posted_on)
        c = classify(t.provider_category, t.provider_category_detailed, t.amount_cents, t.category)
        if c.kind == "spending":
            spending[k][c.category] += -t.amount_cents  # money out counts up; refunds count down
        elif c.kind == "income":
            income[k] += t.amount_cents

    all_first = min(first_day.values()) if first_day else None
    out = []
    for k in keys:
        by_cat = {cat: spending[k][cat] for cat in CATEGORIES if spending[k].get(cat)}
        total = sum(by_cat.values())
        inc = income[k]
        out.append({
            "month": k,
            "spending_cents": total,
            "income_cents": inc,
            "saved_cents": inc - total,
            "savings_rate": round((inc - total) / inc, 4) if inc > 0 else None,
            "by_category": by_cat,
            "has_data": k in first_day,
            # The month history starts in, and the current month, are incomplete.
            "partial": k == keys[-1] or (all_first is not None and k == _month_key(all_first) and all_first.day > 1),
        })
    return out
