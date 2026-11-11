"""Recurring monthly bills and subscriptions.

Two sources:

1. Detected from your transactions. For each merchant, charges are chained into
   a series when the next one comes 25-35 days after the previous and its amount
   is within 25%. A series counts as a recurring bill only if it looks like a
   subscription, not a shopping habit:
   - every step between charges is within 1%, except at most one price change
     (e.g. 9.99 -> 11.99), and at least one step is a steady repeat;
   - in habit categories (Food, Shopping, Transport) it needs 3+ months in a row,
     elsewhere 2+.
   One-off purchases at the same merchant (tickets, orders) don't chain.

2. Added by hand (`ManualRecurring`), for bills that never hit your accounts,
   e.g. your share of a phone plan someone else pays via Splitwise.

3. Loan payments: each hand-entered loan's regular monthly payment and due day.

6. Recurring income (kind "income"): paychecks (biweekly or monthly) and monthly
   interest, detected from deposits; amounts may change (raises), and the monthly
   equivalent of a biweekly paycheck is amount x 26 / 12. Expected one-off
   income added by hand (e.g. a bonus every June and December) shows with its
   next expected month.

5. Upcoming periodic expenses (kind "planned"): hand-added bills that come every
   few months (tuition per semester, yearly renewals). Shown with their next due
   date and a monthly set-aside = amount / months in the cycle.

4. Saving & investing: steady monthly transfers into investment or savings
   accounts (same subscription rules), e.g. an automatic brokerage deposit.

Every item has a `kind`: "bill" (spending), "loan" or "saving". Loan payments
and saving are money moving to your own accounts/debts, so they never count as
spending, but they're still money that leaves checking every month.

If a charge was split on Splitwise, the bill shows your share.

Optional private labels (data/recurring_labels.json, git-ignored) give series
friendlier names, e.g. {"merchant": "StreamCo", "max": 5, "label": "Basic plan"}.
"""

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import LoanTerms, ManualRecurring, Transaction
from app.services.spending import canonical, classify, match_split_expenses

MIN_GAP_DAYS, MAX_GAP_DAYS = 25, 35
MAX_PRICE_CHANGE = 0.25  # chaining tolerance
STEADY = 0.01            # a "same price" step: within 1%
HABIT_CATEGORIES = {"Food & groceries", "Personal care & shopping", "Transport & travel"}
# Memberships inside "habit" categories: treated like any other subscription.
MEMBERSHIP_DETAILED = {"PERSONAL_CARE_GYMS_AND_FITNESS_CENTERS"}
SAVING_DETAILED = {"TRANSFER_OUT_INVESTMENT_AND_RETIREMENT_FUNDS", "TRANSFER_OUT_SAVINGS"}
ACTIVE_WITHIN_DAYS = 40  # a monthly bill not seen for longer is shown as possibly cancelled


@dataclass
class RecurringBill:
    kind: str  # "bill" | "loan" | "saving" | "planned" | "income"
    name: str
    merchant: str
    category: str
    amount_cents: int  # latest amount (your share if split)
    last_charged: date | None
    next_expected: date | None
    account: str | None
    source: str  # "detected" | "manual"
    active: bool = True
    charges: list[tuple[date, int]] = field(default_factory=list)
    note: str = ""
    set_aside_cents: int = 0  # planned only: per month
    cadence: str = "monthly"  # "biweekly" | "monthly" | "semiannual" ...
    monthly_cents: int | None = None  # monthly equivalent (income); None = not monthly
    paid_this_month: bool = False  # bills: already charged this calendar month (so already in spending)


def _add_month(d: date) -> date:
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue
    return date(y, m, 28)


def _label_rule(merchant: str, amount_cents: int, labels: list[dict]) -> dict | None:
    for rule in labels:
        if rule.get("merchant", "").lower() != merchant.lower():
            continue
        amt = amount_cents / 100
        if ("min" in rule and amt < rule["min"]) or ("max" in rule and amt > rule["max"]):
            continue
        return rule
    return None


def _looks_like_subscription(s: list[Transaction]) -> bool:
    amounts = [-t.amount_cents for t in s]
    steps = [abs(b - a) / max(a, 1) for a, b in zip(amounts, amounts[1:])]
    steady = sum(1 for x in steps if x <= STEADY)
    changes = len(steps) - steady
    if not steps or steady == 0 or changes > 1:
        return False
    first = s[-1]
    category = classify(first.provider_category, first.provider_category_detailed,
                        first.amount_cents, first.category).category
    habit = category in HABIT_CATEGORIES and first.provider_category_detailed not in MEMBERSHIP_DETAILED
    return len(s) >= (3 if habit else 2)


def load_labels(path: Path | None) -> list[dict]:
    if path and path.exists():
        return json.loads(path.read_text()).get("labels", [])
    return []


def _label(merchant: str, amount_cents: int, labels: list[dict]) -> str:
    rule = _label_rule(merchant, amount_cents, labels)
    return rule["label"] if rule and "label" in rule else merchant


def detect_recurring(session: Session, today: date | None = None,
                     labels_path: Path | None = None) -> list[RecurringBill]:
    today = today or date.today()
    labels = load_labels(labels_path)
    share_by_txn = {m.transaction.id: m.expense.share_cents
                    for m in match_split_expenses(session) if m.transaction is not None}

    by_merchant: dict[str, list[Transaction]] = {}
    for t in session.scalars(select(Transaction).where(Transaction.amount_cents < 0).order_by(Transaction.posted_on)):
        c = classify(t.provider_category, t.provider_category_detailed, t.amount_cents, t.category)
        saving = t.provider_category_detailed in SAVING_DETAILED and not t.category
        if not saving and (c.kind != "spending" or c.category == "Rent"):  # rent is tracked on its own
            continue
        by_merchant.setdefault(t.description.strip(), []).append(t)

    bills = []
    for merchant, txns in by_merchant.items():
        series: list[list[Transaction]] = []
        for t in txns:
            amount = -t.amount_cents
            for s in series:
                last = s[-1]
                gap = (t.posted_on - last.posted_on).days
                change = abs(amount - (-last.amount_cents)) / max(-last.amount_cents, 1)
                if MIN_GAP_DAYS <= gap <= MAX_GAP_DAYS and change <= MAX_PRICE_CHANGE:
                    s.append(t)
                    break
            else:
                series.append([t])
        for s in series:
            if not _looks_like_subscription(s):
                continue
            last = s[-1]
            amount = share_by_txn.get(last.id, -last.amount_cents)
            c = classify(last.provider_category, last.provider_category_detailed, last.amount_cents, last.category)
            changed = -s[-1].amount_cents != -s[0].amount_cents
            notes = []
            if last.id in share_by_txn:
                notes.append(f"your share of {-last.amount_cents / 100:.2f}")
            if changed:
                notes.append(f"was {-s[0].amount_cents / 100:.2f}")
            active = (today - last.posted_on).days <= ACTIVE_WITHIN_DAYS
            rule = _label_rule(merchant, -last.amount_cents, labels) or {}
            is_saving = last.provider_category_detailed in SAVING_DETAILED and not last.category
            bills.append(RecurringBill(
                paid_this_month=(last.posted_on.year, last.posted_on.month) == (today.year, today.month),
                kind="saving" if is_saving else "bill",
                name=_label(merchant, -last.amount_cents, labels),
                merchant=merchant,
                category=canonical(rule.get("category")) or ("Saving & investing" if is_saving else (c.category or "Other")),
                amount_cents=amount,
                last_charged=last.posted_on,
                next_expected=_add_month(last.posted_on) if active else None,
                account=last.account.display_name if last.account else None,
                source="detected",
                active=active,
                charges=[(x.posted_on, -x.amount_cents) for x in s],
                note="; ".join(notes) or ("" if active else "not seen recently: cancelled?"),
            ))

    cycle_months = {"quarterly": 3, "semester": 6, "semiannual": 6, "yearly": 12}
    detected_names = {b.name.lower() for b in bills if b.active}
    for mr in session.scalars(select(ManualRecurring)):
        if mr.name.lower() in detected_names:
            continue  # now found in your charges: the detected version replaces the hand-added one
        if mr.category == "Income":  # expected income added by hand, e.g. a bonus
            months = sorted(int(x) for x in (mr.due_note or "").split(",") if x.strip().isdigit())
            nxt = mr.next_due or _next_in_months(today, months)
            bills.append(RecurringBill(
                kind="income", name=mr.name, merchant=mr.name, category="Income",
                amount_cents=mr.amount_cents, last_charged=None, next_expected=nxt,
                account=mr.paid_via, source="manual", cadence=mr.cadence or "once",
                note="; ".join(x for x in (
                    _month_names(months) and f"every {_month_names(months)}",
                    "amount not set yet" if not mr.amount_cents else "", mr.note) if x),
            ))
            continue
        if mr.cadence in cycle_months:
            months = cycle_months[mr.cadence]
            due_text = mr.due_note or (mr.next_due.isoformat() if mr.next_due else "")
            bills.append(RecurringBill(
                kind="planned", name=mr.name, merchant=mr.name, category=canonical(mr.category),
                amount_cents=mr.amount_cents, last_charged=None, next_expected=mr.next_due,
                account=mr.paid_via, source="manual",
                note="; ".join(x for x in (f"every {mr.cadence}", f"due {due_text}" if due_text else "", mr.note) if x),
                set_aside_cents=round(mr.amount_cents / months),
            ))
            continue
        nxt = None
        if mr.day_of_month:
            nxt = date(today.year, today.month, min(mr.day_of_month, 28))
            if nxt < today:
                nxt = _add_month(nxt)
        bills.append(RecurringBill(
            kind="bill", name=mr.name, merchant=mr.name, category=canonical(mr.category), amount_cents=mr.amount_cents,
            last_charged=None, next_expected=nxt, account=mr.paid_via, source="manual", note=mr.note or "",
        ))

    for lt in session.scalars(select(LoanTerms)):
        due = date(today.year, today.month, min(lt.payment_day, 28))
        if due < today:
            due = _add_month(due)
        recent = []
        if lt.payment_match:
            from app.services.loans import find_tracked_payments

            recent = find_tracked_payments(session, lt, today)
        note = "regular payment"
        if recent:
            note += "; you've paid " + ", ".join(f"{p.amount_cents / 100:.0f}" for p in recent[-3:])
        bills.append(RecurringBill(
            kind="loan", name=lt.account.display_name, merchant=lt.account.display_name,
            category="Loan payment", amount_cents=lt.monthly_payment_cents, last_charged=None,
            next_expected=due if lt.account.balance_cents > 0 else None,
            account=lt.account.institution.name if lt.account.institution else None,
            source="loan", active=lt.account.balance_cents > 0, note=note,
        ))

    bills.extend(_detect_income(session, today, labels))

    order = {"income": -1, "bill": 0, "loan": 1, "saving": 2, "planned": 3}
    bills.sort(key=lambda b: (order[b.kind], not b.active, -b.amount_cents))
    return bills


INCOME_DETAILED = {"INCOME_SALARY", "INCOME_WAGES", "INCOME_INTEREST_EARNED"}
_MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _month_names(months: list[int]) -> str:
    return " & ".join(_MONTH_ABBR[m - 1] for m in months)


def _next_in_months(today: date, months: list[int]) -> date | None:
    """First day of the next listed month on or after this month."""
    for add in range(13):
        m = (today.month - 1 + add) % 12 + 1
        y = today.year + (today.month - 1 + add) // 12
        if m in months:
            return date(y, m, 1)
    return None


def _detect_income(session: Session, today: date, labels: list[dict] | None = None) -> list[RecurringBill]:
    """Paychecks and interest: deposits from the same payer on a regular rhythm."""
    by_payer: dict[str, list[Transaction]] = {}
    for t in session.scalars(select(Transaction).where(Transaction.amount_cents > 0).order_by(Transaction.posted_on)):
        if t.provider_category_detailed in INCOME_DETAILED and not t.category:
            by_payer.setdefault(t.description.strip(), []).append(t)
    out = []
    for payer, txns in by_payer.items():
        if len(txns) < 2:
            continue
        gaps = sorted((b.posted_on - a.posted_on).days for a, b in zip(txns, txns[1:]))
        median = gaps[len(gaps) // 2]
        if 12 <= median <= 16:
            cadence, step, per_month = "biweekly", timedelta(days=14), 26 / 12
        elif 25 <= median <= 35:
            cadence, step, per_month = "monthly", None, 1
        else:
            continue
        last = txns[-1]
        nxt = last.posted_on + step if step else _add_month(last.posted_on)
        active = (today - last.posted_on).days <= (20 if cadence == "biweekly" else ACTIVE_WITHIN_DAYS)
        first_amt = txns[0].amount_cents
        note = f"was {first_amt / 100:,.2f}" if first_amt != last.amount_cents else ""
        out.append(RecurringBill(
            kind="income", name=_label(payer, last.amount_cents, labels or []), merchant=payer,
            category="Income", amount_cents=last.amount_cents,
            last_charged=last.posted_on, next_expected=nxt if active else None,
            account=last.account.display_name if last.account else None, source="detected",
            active=active, cadence=cadence, monthly_cents=round(last.amount_cents * per_month),
            charges=[(x.posted_on, x.amount_cents) for x in txns], note=note,
        ))
    return out


def monthly_total_cents(bills: list[RecurringBill], kind: str | None = "bill") -> int:
    """Monthly total of active items of one kind (default: bills); kind=None for every
    monthly outflow (bills, loans, saving). Planned items count their monthly set-aside."""
    if kind == "planned":
        return sum(b.set_aside_cents for b in bills if b.kind == "planned")
    if kind == "income":
        return sum(b.monthly_cents or 0 for b in bills if b.kind == "income" and b.active)
    return sum(b.amount_cents for b in bills
               if b.active and b.kind not in ("planned", "income") and (kind is None or b.kind == kind))
