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

Shared expenses (imported from Splitwise, see `SplitExpense`):
- You paid it: the matching bank/card transaction (same amount, dated up to 31
  days before to 7 days after the Splitwise date, closest first) counts only YOUR
  share. The rest is money owed to you, not spending.
- Someone else paid: your share is added as spending in that month, even though
  no charge appears in your accounts.
- A paid expense with no matching transaction (e.g. paid from an unlinked
  account) still adds your share, and is listed as unmatched for review.

Known limit: loan payments are all treated as transfers; their interest isn't counted yet.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from datetime import timedelta

from app.db.models import SplitExpense, Transaction

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


MATCH_BEFORE_DAYS = 31  # Splitwise entries are often logged after the charge (e.g. last month's bill)
MATCH_AFTER_DAYS = 7    # ...or a few days before it posts at the bank


@dataclass
class SplitMatch:
    expense: SplitExpense
    transaction: Transaction | None  # None: someone else paid, or no matching charge found


def match_split_expenses(session: Session) -> list[SplitMatch]:
    """Pair each shared expense you paid with the bank/card transaction that paid it.

    A transaction is used at most once. Candidates: money out of exactly
    `you_paid`, classified as spending, inside the date window; the closest date wins.
    """
    used: set[int] = set()
    matches = []
    for e in session.scalars(select(SplitExpense).order_by(SplitExpense.spent_on, SplitExpense.id)):
        if e.you_paid_cents <= 0:
            matches.append(SplitMatch(e, None))
            continue
        candidates = [
            t for t in session.scalars(select(Transaction).where(
                Transaction.amount_cents == -e.you_paid_cents,
                Transaction.posted_on >= e.spent_on - timedelta(days=MATCH_BEFORE_DAYS),
                Transaction.posted_on <= e.spent_on + timedelta(days=MATCH_AFTER_DAYS),
            ))
            if t.id not in used and classify(t.provider_category, t.provider_category_detailed,
                                             t.amount_cents, t.category).kind == "spending"
        ]
        candidates.sort(key=lambda t: (abs((t.posted_on - e.spent_on).days), t.id))
        best = candidates[0] if candidates else None
        if best:
            used.add(best.id)
        matches.append(SplitMatch(e, best))
    return matches


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

    # Shared expenses: count only your share.
    unmatched = defaultdict(int)
    for sm in match_split_expenses(session):
        e = sm.expense
        if sm.transaction is not None:
            t = sm.transaction
            k = _month_key(t.posted_on)  # adjust the month the charge actually landed in
            if k in spending:
                cat = classify(t.provider_category, t.provider_category_detailed, t.amount_cents, t.category).category
                spending[k][cat] -= e.you_paid_cents  # take out the full charge...
                spending[k][e.category] += e.share_cents  # ...and count only your share
        else:
            k = _month_key(e.spent_on)
            if k in spending:
                spending[k][e.category] += e.share_cents  # someone else paid (or unlinked account)
                first_day[k] = min(first_day.get(k, e.spent_on), e.spent_on)
                if e.you_paid_cents > 0:
                    unmatched[k] += 1

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
            "unmatched_shared": unmatched[k],
            # The month history starts in, and the current month, are incomplete.
            "partial": k == keys[-1] or (all_first is not None and k == _month_key(all_first) and all_first.day > 1),
        })
    return out
