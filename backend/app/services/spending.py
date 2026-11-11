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

Household rent rule (optional, `RentRule`, kept in git-ignored data/household.json):
your rent is a fixed share of a fixed base rent, every month, whoever paid the
landlord. Then:
- Rent = `your_share` in every month that has data.
- Rent payments in your accounts are paying the landlord for the household, and
  settle-ups with housemates are transfers, so neither counts as spending.
- A payment above the base by up to 25% includes utilities billed with the rent:
  your part (excess / people) counts as Bills & utilities, unless a Splitwise
  rent entry for that payment already says what your utilities share was.
- A payment more than 25% above the base is flagged as "unexplained" and its
  excess counts in full as Other until you say what it was.

Known limit: loan payments are all treated as transfers; their interest isn't counted yet.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import SplitExpense, Transaction

# Display order is fixed so each category keeps the same colour everywhere
# (8 colours + grey "Other": the most a chart can keep distinguishable).
CATEGORIES = [
    "Rent", "Food & groceries", "Personal care & shopping", "Transport & travel", "Entertainment",
    "Bills & subscriptions", "Education", "Health care", "Other",
]

# Older names still accepted everywhere (and migrated on startup).
CATEGORY_ALIASES = {
    "Food": "Food & groceries",
    "Shopping": "Personal care & shopping",
    "Personal care": "Personal care & shopping",
    "Transport": "Transport & travel",
    "Travel": "Transport & travel",
    "Bills & utilities": "Bills & subscriptions",
    "Subscriptions": "Bills & subscriptions",
    "Health": "Health care",
    "Health & care": "Health care",
}

# Finer budget lines inside a category ("sub"), e.g. groceries vs eating out.
# You can also use these names directly as a category for a transaction.
SUB_LINES = {
    "Groceries": ("Food & groceries", "groceries"),
    "Fuel": ("Transport & travel", "fuel"),
}
_DETAILED_SUB = {
    "FOOD_AND_DRINK_GROCERIES": "groceries",
    "GENERAL_MERCHANDISE_SUPERSTORES": "groceries",  # warehouse clubs, big-box stores (their gas is fuel)
    "TRANSPORTATION_GAS": "fuel",
    "GENERAL_SERVICES_AUTOMOTIVE": "fuel",
}


def canonical(category: str | None) -> str | None:
    """Map an older or alias category name (or a sub-line name) to the current category."""
    if not category:
        return category
    if category in SUB_LINES:
        return SUB_LINES[category][0]
    return CATEGORY_ALIASES.get(category, category)


_PRIMARY_TO_CATEGORY = {
    "FOOD_AND_DRINK": "Food & groceries",
    "GENERAL_MERCHANDISE": "Personal care & shopping",
    "HOME_IMPROVEMENT": "Personal care & shopping",
    "PERSONAL_CARE": "Personal care & shopping",
    "TRANSPORTATION": "Transport & travel",
    "TRAVEL": "Transport & travel",
    "ENTERTAINMENT": "Entertainment",
    "RENT_AND_UTILITIES": "Bills & subscriptions",  # rent itself is picked out below
    "MEDICAL": "Health care",
    "EDUCATION": "Education",
    "GENERAL_SERVICES": "Bills & subscriptions",  # insurance, software subscriptions... (see detailed)
    "GOVERNMENT_AND_NON_PROFIT": "Other",
    "BANK_FEES": "Other",
}
# Finer rules by Plaid's detailed category, checked before the primary ones.
_DETAILED_TO_CATEGORY = {
    "GENERAL_MERCHANDISE_SUPERSTORES": "Food & groceries",
    "GENERAL_SERVICES_AUTOMOTIVE": "Transport & travel",
    "GENERAL_SERVICES_EDUCATION": "Education",
    "GENERAL_SERVICES_CHILDCARE": "Other",
    "GENERAL_SERVICES_POSTAGE_AND_SHIPPING": "Other",
}
_TRANSFER_PRIMARIES = {"TRANSFER_IN", "TRANSFER_OUT", "LOAN_PAYMENTS"}


@dataclass
class Classified:
    kind: str  # "spending" | "income" | "transfer"
    category: str | None = None
    sub: str | None = None  # finer budget line inside the category, e.g. "groceries"


def classify(primary: str | None, detailed: str | None, amount_cents: int,
             user_category: str | None = None) -> Classified:
    """Decide what a transaction means for spending and savings."""
    if user_category:
        if user_category in ("Income", "Transfer"):
            return Classified(user_category.lower())
        if user_category in SUB_LINES:
            return Classified("spending", *SUB_LINES[user_category])
        return Classified("spending", canonical(user_category))
    if primary in _TRANSFER_PRIMARIES:
        return Classified("transfer")
    if primary == "INCOME":
        if detailed == "INCOME_RENTAL":  # cancels a duplicate rent entry (see module docstring)
            return Classified("spending", "Rent")
        return Classified("income") if amount_cents > 0 else Classified("transfer")
    if detailed == "RENT_AND_UTILITIES_RENT":
        return Classified("spending", "Rent")
    sub = _DETAILED_SUB.get(detailed)
    if detailed in _DETAILED_TO_CATEGORY:
        return Classified("spending", _DETAILED_TO_CATEGORY[detailed], sub)
    if primary in _PRIMARY_TO_CATEGORY:
        return Classified("spending", _PRIMARY_TO_CATEGORY[primary], sub)
    # Unknown or missing category: money out is spending, money in is left out.
    return Classified("spending", "Other") if amount_cents < 0 else Classified("transfer")


@dataclass
class RentRule:
    base_cents: int        # the household's monthly rent
    your_share_cents: int  # your part of it
    people: int = 2

    @classmethod
    def load(cls, path) -> "RentRule | None":
        import json
        from pathlib import Path

        p = Path(path)
        if not p.exists():
            return None
        r = json.loads(p.read_text()).get("rent")
        if not r:
            return None
        from app.services.money import to_cents

        return cls(to_cents(str(r["base_monthly"])), to_cents(str(r["your_share_monthly"])), int(r.get("people", 2)))


UTILITIES_TOLERANCE = 0.25


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


@dataclass
class SpendItem:
    day: date
    category: str
    cents: int  # positive = spending, negative = refund / taken back out
    sub: str | None = None


@dataclass
class Collected:
    spend: list[SpendItem] = field(default_factory=list)
    income: list[tuple[date, int, str]] = field(default_factory=list)  # (day, cents, description)
    data_days: set[date] = field(default_factory=set)  # days with any data (has_data / partial)
    unmatched: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    flags: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))


def collect_spending(session: Session, start: date, end: date, rent_rule: RentRule | None = None) -> Collected:
    """Every spending and income item between start and end (inclusive), after shared
    expenses (Splitwise) and the household rent rule are applied. Monthly charts and
    budgets are both built from this one list, so they always agree."""
    out = Collected()
    rows = session.scalars(select(Transaction).where(Transaction.posted_on >= start,
                                                     Transaction.posted_on <= end)).all()
    rent_paid: dict[date, int] = defaultdict(int)  # net household rent paid, per day (rule only)
    for t in rows:
        out.data_days.add(t.posted_on)
        if t.parts():  # your own split of one payment across categories
            for cat, cents in t.parts().items():
                sub = SUB_LINES.get(cat, (None, None))[1]
                cat = canonical(cat)
                if rent_rule and cat == "Rent":
                    rent_paid[t.posted_on] += cents
                else:
                    out.spend.append(SpendItem(t.posted_on, cat, cents, sub))
            continue
        c = classify(t.provider_category, t.provider_category_detailed, t.amount_cents, t.category)
        if c.kind == "spending" and rent_rule and c.category == "Rent":
            rent_paid[t.posted_on] += -t.amount_cents  # household rent payment: handled below
        elif c.kind == "spending":
            out.spend.append(SpendItem(t.posted_on, c.category, -t.amount_cents, c.sub))
        elif c.kind == "income":
            out.income.append((t.posted_on, t.amount_cents, t.description))

    # Shared expenses: count only your share.
    rent_explained: set[date] = set()  # rent payments a Splitwise entry already accounts for

    def add_parts(day, parts, sub=None):
        for part_cat, cents in parts.items():
            part_sub = SUB_LINES.get(part_cat, (None, sub))[1]
            part_cat = canonical(part_cat)
            if rent_rule and part_cat == "Rent":
                continue  # the fixed monthly share covers rent
            out.spend.append(SpendItem(day, part_cat, cents, part_sub))

    for sm in match_split_expenses(session):
        e = sm.expense
        if sm.transaction is not None:
            t = sm.transaction
            if not (start <= t.posted_on <= end):
                continue
            c = classify(t.provider_category, t.provider_category_detailed, t.amount_cents, t.category)
            if rent_rule and c.category == "Rent":
                rent_explained.add(t.posted_on)
            else:
                out.spend.append(SpendItem(t.posted_on, c.category, -e.you_paid_cents, c.sub))  # take out the charge...
            add_parts(t.posted_on, e.parts(), c.sub)  # ...and count only your share
        elif start <= e.spent_on <= end:
            add_parts(e.spent_on, e.parts())  # someone else paid (or unlinked account)
            out.data_days.add(e.spent_on)
            if e.you_paid_cents > 0:
                out.unmatched[_month_key(e.spent_on)] += 1

    if rent_rule:
        for day, paid in sorted(rent_paid.items()):
            excess = paid - rent_rule.base_cents
            if day in rent_explained or excess <= 0:
                continue
            if excess <= rent_rule.base_cents * UTILITIES_TOLERANCE:
                out.spend.append(SpendItem(day, "Bills & subscriptions", round(excess / rent_rule.people)))
            else:
                out.spend.append(SpendItem(day, "Other", excess))
                out.flags[_month_key(day)].append(
                    f"rent payment on {day} was {excess / 100:,.2f} above the base rent (unexplained)")
        # Your fixed rent share, dated the 1st of each month that has data and
        # starts inside the window (rent is due on the 1st; a window starting
        # mid-month doesn't include that month's rent).
        for k in sorted({_month_key(d) for d in out.data_days}):
            first = date(int(k[:4]), int(k[5:]), 1)
            if start <= first <= end:
                out.spend.append(SpendItem(first, "Rent", rent_rule.your_share_cents))
    return out


def monthly_summary(session: Session, months: int = 6, today: date | None = None,
                    rent_rule: RentRule | None = None) -> list[dict]:
    """The last `months` calendar months (oldest first), each with:
    spending_cents, income_cents, saved_cents, savings_rate (None without income),
    by_category {name: cents}, by_sub {"groceries": cents, ...}, has_data / partial flags.
    """
    today = today or date.today()
    keys = []
    y, m = today.year, today.month
    for _ in range(months):
        keys.append(f"{y:04d}-{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    keys.reverse()
    first_of_range = date(int(keys[0][:4]), int(keys[0][5:]), 1)
    end_of_range = max(today, _add_months_end(keys[-1]))
    col = collect_spending(session, first_of_range, end_of_range, rent_rule)

    spending = {k: defaultdict(int) for k in keys}
    subs = {k: defaultdict(int) for k in keys}
    income = dict.fromkeys(keys, 0)
    for it in col.spend:
        k = _month_key(it.day)
        if k in spending:
            spending[k][it.category] += it.cents
            if it.sub:
                subs[k][it.sub] += it.cents
    for day, cents, _desc in col.income:
        k = _month_key(day)
        if k in income:
            income[k] += cents
    data_months = {_month_key(d) for d in col.data_days}
    all_first = min(col.data_days) if col.data_days else None

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
            "by_sub": dict(subs[k]),
            "has_data": k in data_months,
            "unmatched_shared": col.unmatched[k],
            "flags": col.flags[k],
            # The month history starts in, and the current month, are incomplete.
            "partial": k == keys[-1] or (all_first is not None and k == _month_key(all_first) and all_first.day > 1),
        })
    return out


def _add_months_end(key: str) -> date:
    """Last day of the month `key` ("YYYY-MM")."""
    y, m = int(key[:4]), int(key[5:])
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return nxt - timedelta(days=1)
